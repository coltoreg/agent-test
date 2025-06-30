from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth
import os
import boto3
import json
import logging
import cfnresponse
import time

HOST = os.environ.get("COLLECTION_HOST")
VECTOR_INDEX_NAME = os.environ.get("VECTOR_INDEX_NAME")
VECTOR_FIELD_NAME = os.environ.get("VECTOR_FIELD_NAME")
DOCUMENT_INDEX = os.environ.get("DOCUMENT_INDEX")
DDL_INDEX = os.environ.get("DDL_INDEX")
QUESTION_SQL_INDEX = os.environ.get("QUESTION_SQL_INDEX")
REGION_NAME = os.environ.get("REGION_NAME")
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def log(message):
    logger.info(message)


def lambda_handler(event, context):
    """
    Lambda handler to create OpenSearch Index
    """
    log(f"Event: {json.dumps(event)}")

    session = boto3.Session()

    # Get STS client from session
    sts_client = session.client("sts")

    # Get caller identity
    caller_identity = sts_client.get_caller_identity()

    # Print the caller identity information
    log(f"Caller Identity: {caller_identity}")

    # Specifically, print the ARN of the caller
    log(f"ARN: {caller_identity['Arn']}")

    creds = session.get_credentials()

    # Get STS client from session
    sts_client = session.client("sts")

    # Get caller identity
    caller_identity = sts_client.get_caller_identity()

    # Print the caller identity information
    log(f"Caller Identity: {caller_identity}")

    # Specifically, print the ARN of the caller
    log(f"ARN: {caller_identity['Arn']}")

    log(f"HOST: {HOST}")
    host = HOST.split("//")[1]

    region = REGION_NAME
    service = "aoss"
    status = cfnresponse.SUCCESS
    response = {}

    try:
        auth = AWSV4SignerAuth(creds, region, service)

        client = OpenSearch(
            hosts=[{"host": host, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            pool_maxsize=20,
        )
        index_name = VECTOR_INDEX_NAME

        if event["RequestType"] == "Create":
            log(f"Creating Bedrock vector index: {index_name}")

            # 創建 Bedrock 向量索引
            index_body = {
                # This section contains specific index-level configurations.
                "settings": {
                    # This setting enables you to perform real-time k-NN search on an index. k-NN search lets you find the "k" closest points in your vector space by Euclidean distance or cosine similarity.
                    "index.knn": True,
                    "index.knn.algo_param.ef_search": 512,
                },
                "mappings": {
                    "properties": {  # Properties section is where you define the fields (properties) of the documents that will be stored in the index.
                        VECTOR_FIELD_NAME: {  # Name of the field
                            # This specifies that the field is a k-NN vector type. This type is provided by the k-NN plugin and is necessary for performing nearest neighbor searches on the data.
                            "type": "knn_vector",
                            "dimension": 1536,
                            "method": {  # 'method' contains settings for the algorithm used for k-NN calculations. Default method is l2(stands for Euclidean distance). You can also use cosine similarity.
                                # Space in which distance calculations will be done. "l2" stands for L2 space (Euclidean distance)
                                "space_type": "innerproduct",
                                # Underlying engine to perform the vector calculations. FAISS is a library for efficient similarity search and clustering of dense vectors. The alternative is "nmslib".
                                "engine": "FAISS",
                                # This specifies the exact algorithm FAISS will use for k-NN calculations. HNSW stands for Hierarchical Navigable Small World, which is efficient for similarity searches.
                                "name": "hnsw",
                                "parameters": {
                                    "m": 16,
                                    "ef_construction": 512,
                                },
                            },
                        },
                        "AMAZON_BEDROCK_METADATA": {"type": "text", "index": False},
                        "AMAZON_BEDROCK_TEXT_CHUNK": {"type": "text"},
                        "id": {"type": "text"},
                    }
                },
            }

            response = client.indices.create(index_name, body=index_body)
            log(f"Bedrock index creation response: {response}")
            
            # 創建 Vanna 所需的三個 index
            log("Now creating Vanna indices...")
            
            # 1. 創建文檔索引
            if not client.indices.exists(DOCUMENT_INDEX):
                doc_mapping = {
                    "mappings": {
                        "properties": {
                            "doc": {"type": "text"}
                        }
                    }
                }
                try:
                    doc_response = client.indices.create(DOCUMENT_INDEX, body=doc_mapping)
                    log(f"Created document index: {DOCUMENT_INDEX}")
                    log(f"Response: {doc_response}")
                except Exception as e:
                    log(f"Error creating document index {DOCUMENT_INDEX}: {str(e)}")
            else:
                log(f"Document index {DOCUMENT_INDEX} already exists")
            
            # 2. 創建 DDL 索引
            if not client.indices.exists(DDL_INDEX):
                ddl_mapping = {
                    "mappings": {
                        "properties": {
                            "ddl": {"type": "text"}
                        }
                    }
                }
                try:
                    ddl_response = client.indices.create(DDL_INDEX, body=ddl_mapping)
                    log(f"Created DDL index: {DDL_INDEX}")
                    log(f"Response: {ddl_response}")
                except Exception as e:
                    log(f"Error creating DDL index {DDL_INDEX}: {str(e)}")
            else:
                log(f"DDL index {DDL_INDEX} already exists")
            
            # 3. 創建 問題SQL 索引
            if not client.indices.exists(QUESTION_SQL_INDEX):
                q_sql_mapping = {
                    "mappings": {
                        "properties": {
                            "question": {"type": "text"},
                            "sql": {"type": "text"}
                        }
                    }
                }
                try:
                    q_sql_response = client.indices.create(QUESTION_SQL_INDEX, body=q_sql_mapping)
                    log(f"Created Question/SQL index: {QUESTION_SQL_INDEX}")
                    log(f"Response: {q_sql_response}")
                except Exception as e:
                    log(f"Error creating Question/SQL index {QUESTION_SQL_INDEX}: {str(e)}")
            else:
                log(f"Question/SQL index {QUESTION_SQL_INDEX} already exists")

            # wait 1 minute
            log("Sleeping for 1 minutes to let indices create.")
            # nosemgrep: <arbitrary-sleep Message: time.sleep() call>
            time.sleep(60)  # nosem: arbitrary-sleep

        elif event["RequestType"] == "Delete":
            # 刪除 Bedrock 索引
            log(f"Deleting Bedrock index: {index_name}")
            if client.indices.exists(index_name):
                response = client.indices.delete(index_name)
                log(f"Response: {response}")
            
            # 刪除 Vanna 索引
            log("Now deleting Vanna indices...")
            
            # 刪除文檔索引
            if client.indices.exists(DOCUMENT_INDEX):
                try:
                    doc_response = client.indices.delete(DOCUMENT_INDEX)
                    log(f"Deleted document index: {DOCUMENT_INDEX}")
                    log(f"Response: {doc_response}")
                except Exception as e:
                    log(f"Error deleting document index {DOCUMENT_INDEX}: {str(e)}")
            
            # 刪除 DDL 索引
            if client.indices.exists(DDL_INDEX):
                try:
                    ddl_response = client.indices.delete(DDL_INDEX)
                    log(f"Deleted DDL index: {DDL_INDEX}")
                    log(f"Response: {ddl_response}")
                except Exception as e:
                    log(f"Error deleting DDL index {DDL_INDEX}: {str(e)}")
            
            # 刪除 問題/SQL 索引
            if client.indices.exists(QUESTION_SQL_INDEX):
                try:
                    q_sql_response = client.indices.delete(QUESTION_SQL_INDEX)
                    log(f"Deleted Question/SQL index: {QUESTION_SQL_INDEX}")
                    log(f"Response: {q_sql_response}")
                except Exception as e:
                    log(f"Error deleting Question/SQL index {QUESTION_SQL_INDEX}: {str(e)}")
        else:
            log("Continuing without action.")

    except Exception as e:
        logging.error("Exception: %s" % e, exc_info=True)
        status = cfnresponse.FAILED

    finally:
        cfnresponse.send(event, context, status, response)

    return {
        "statusCode": 200,
        "body": json.dumps("Create index lambda ran successfully."),
    }