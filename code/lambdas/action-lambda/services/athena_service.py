from utils.logger import setup_logger
from utils.exceptions import ValidationError, ExternalAPIError

from sqlalchemy import create_engine
from llama_index.core import SQLDatabase, ServiceContext, VectorStoreIndex
from llama_index.core.objects import ObjectIndex, SQLTableNodeMapping, SQLTableSchema
from llama_index.core.indices.struct_store import SQLTableRetrieverQueryEngine
from llama_index.embeddings.bedrock import BedrockEmbedding
from llama_index.core.prompts import PromptTemplate, Prompt
from llama_index.core.schema import TextNode

import csv
import json
from datetime import datetime
import zoneinfo

from services.connections import Connections
from services.prompt_templates import SQL_TEMPLATE_STR, RESPONSE_TEMPLATE_STR, table_details

logger = setup_logger(__name__)

class AthenaService:
    def __init__(self):
        self.conn = Connections()
        self.query_engine, self.obj_index = self._initialize_query_engine()

    def _initialize_query_engine(self):
        try:
            logger.info("Initializing Athena query engine with credentials...")

            sql_database = self._create_sql_database()

            embed_model = BedrockEmbedding(
                client=self.conn.bedrock_client(),
                model_name="amazon.titan-embed-text-v1"
            )
            llm = self.conn.bedrock_llm(model_name="ClaudeInstant", max_tokens=1024)

            service_context = ServiceContext.from_defaults(llm=llm, embed_model=embed_model)

            path = self.conn.env.FEWSHOT_EXAMPLES_PATH
            self.few_shot_retriever, self.data_dict = self._load_few_shot_retriever(path)

            sql_prompt = PromptTemplate(
                SQL_TEMPLATE_STR,
                function_mappings={"few_shot_examples": self._few_shot_examples_fn},
            )

            response_prompt = Prompt(RESPONSE_TEMPLATE_STR)

            table_node_mapping = SQLTableNodeMapping(sql_database)
            table_schema_objs = [
                SQLTableSchema(table_name=table, context_str=table_details[table])
                for table in list(sql_database._all_tables)
                if table in table_details
            ]

            obj_index = ObjectIndex.from_objects(
                table_schema_objs,
                table_node_mapping,
                VectorStoreIndex,
                service_context=service_context,
            )

            query_engine = SQLTableRetrieverQueryEngine(
                sql_database,
                obj_index.as_retriever(similarity_top_k=5),
                service_context=service_context,
                text_to_sql_prompt=sql_prompt,
                response_synthesis_prompt=response_prompt,
            )

            logger.info("Athena query engine initialized successfully.")
            return query_engine, obj_index

        except Exception as e:
            logger.exception("Failed to initialize Athena query engine.")
            raise ExternalAPIError("Athena query engine initialization failed.") from e

    def _create_sql_database(self):
        creds = self.conn.athena_credentials()

        tz = zoneinfo.ZoneInfo("Asia/Taipei")
        now_taipei = datetime.now(tz)
        today = now_taipei.strftime("%Y-%m-%d")
        s3_staging_dir = f"s3://{self.conn.env.ATHENA_BUCKET_NAME}/inv_fetch/{today}/"

        conn_url = (
            f"awsathena+rest://{creds['access_key']}:{creds['secret_key']}"
            f"@athena.{self.conn.env.AWS_FBMAPPING_REGION}.amazonaws.com/"
            f"{self.conn.env.TEXT2SQL_DATABASE}"
            f"?s3_staging_dir={s3_staging_dir}"
        )

        if creds.get("session_token"):
            conn_url += f"&aws_session_token={creds['session_token']}"

        engine = create_engine(conn_url)
        return SQLDatabase(engine, sample_rows_in_table_info=2)

    def _load_few_shot_retriever(self, fewshot_examples_path):
        few_shot_nodes = []
        data_dict = {}

        with open(fewshot_examples_path, newline="", encoding="utf-8-sig") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                question = row["example_input_question"]
                data_dict[question] = row
                few_shot_nodes.append(TextNode(text=json.dumps(question)))

        embed_model = BedrockEmbedding(
            client=self.conn.bedrock_client(),
            model_name="amazon.titan-embed-text-v1"
        )
        service_context = ServiceContext.from_defaults(embed_model=embed_model, llm=None)
        index = VectorStoreIndex(few_shot_nodes, service_context=service_context)
        return index.as_retriever(similarity_top_k=2), data_dict

    def _few_shot_examples_fn(self, **kwargs):
        query_str = kwargs.get("query_str", "")
        retrieved_nodes = self.few_shot_retriever.retrieve(query_str)

        if not retrieved_nodes:
            return "No example set provided"

        examples = []
        for node in retrieved_nodes:
            content = json.loads(node.get_content())
            raw_dict = self.data_dict.get(content, {})
            formatted = "\n".join(f"{k.capitalize()}: {v}" for k, v in raw_dict.items())
            examples.append(formatted)

        return "\n\n".join(examples)

    def execute_query(self, query_text: str) -> dict:
        logger.info(f"Running query: {query_text}")
        try:
            if not query_text:
                raise ValidationError("Query text must not be empty.")

            result = self.query_engine.query(query_text)

            logger.info(f"Query executed. SQL: {result.metadata.get('sql_query')}")
            logger.info(f"Response: {result.response}")

            return {
                "sql_query": result.metadata.get("sql_query"),
                "answer": result.response
            }

        except ValidationError:
            raise
        except Exception as e:
            logger.exception("Error executing market share query.")
            raise ExternalAPIError("Failed to query Athena.") from e