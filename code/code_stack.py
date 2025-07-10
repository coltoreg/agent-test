import os
import sys
import os.path as path
import json
import hashlib
from aws_cdk import (
    CustomResource,
    custom_resources as cr,
    CfnResource,
    Duration,
    Size,
    Stack,
    Aws,
    RemovalPolicy,
    CfnOutput,
    Tags,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_kms as kms,
    aws_iam as iam,
    aws_s3 as s3,
    aws_lambda as lambda_,
    aws_s3_deployment as s3deploy,
    aws_ecs_patterns as ecs_patterns,
    aws_opensearchserverless as opensearchserverless,
    aws_bedrock as bedrock,
    BundlingOptions,
    DockerImage,
    aws_logs as logs,
    aws_cloudwatch as cloudwatch,
)
from constructs import Construct
from aws_cdk.aws_ecr_assets import Platform
from cdk_nag import NagSuppressions

# sys.path.append(os.path.join(os.path.dirname(__file__), "..", "assets"))
# from agent_prompts.agent_prompts import PREPROCESSING_TEMPLATE, ORCHESTRATION_TEMPLATE

# 請先在 .env 中設定本地架構
arch = os.getenv("TARGET_ARCH", "x86_64").lower()
if arch == "x86_64":
    compatible_arch = lambda_.Architecture.X86_64
    compatible_ecs_arch = ecs.CpuArchitecture.X86_64
    ecr_image_platform = Platform.LINUX_AMD64
    lambda_layer_arch = "manylinux2014_x86_64"
elif arch == "arm_64":
    compatible_arch = lambda_.Architecture.ARM_64
    compatible_ecs_arch = ecs.CpuArchitecture.ARM64
    ecr_image_platform = Platform.LINUX_ARM64
    lambda_layer_arch = "manylinux2014_aarch64"
else:
    raise ".env setup error"

class CodeStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # 生成唯一标识符 (基于 account_id 和 region 的 hash)
        #unique_id = hashlib.md5(f"{Aws.ACCOUNT_ID}-{Aws.REGION}".encode()).hexdigest()[:8]
        unique_id = '738b3a45' # 這是為了避免在本地開發時出現錯誤
        self.unique_suffix = unique_id
        
        # 缩短 stack name 用于资源命名 (最多20字符)
        self.short_stack_name = construct_id[:20] if len(construct_id) <= 20 else construct_id[:17] + unique_id[:3]
        
        config = self.get_config()
        logging_context = config["logging"]
        kms_key = self.create_kms_key()
        agent_assets_bucket = self.create_data_source_bucket(kms_key)
        self.upload_files_to_s3(agent_assets_bucket)

        self.lambda_runtime = lambda_.Runtime.PYTHON_3_12

        # boto3_layer = self.create_lambda_layer("boto3_layer")
        opensearch_layer = self.create_lambda_layer("opensearch_layer")

        agent_resource_role = self.create_agent_execution_role(agent_assets_bucket)

        (
            cfn_collection,
            vector_field_name,
            vector_index_name,
            lambda_cr,
        ) = self.create_opensearch_index(agent_resource_role, opensearch_layer, agent_assets_bucket)
        
        # 移動順序為使用 opensearch host
        agent_executor_lambda = self.create_agent_executor_lambda(
            agent_assets_bucket,
            kms_key,
            logging_context,
            cfn_collection
        )

        knowledge_base, agent_resource_role_arn = self.create_knowledgebase(
            vector_field_name,
            vector_index_name,
            cfn_collection,
            agent_resource_role,
            lambda_cr,
        )
        cfn_data_source = self.create_agent_data_source(
            knowledge_base, agent_assets_bucket
        )

        agent = self.create_bedrock_agent(
            agent_executor_lambda,
            agent_assets_bucket,
            agent_resource_role,
            knowledge_base,
        )

        invoke_lambda = self.create_bedrock_agent_invoke_lambda(
            agent, agent_assets_bucket
        )

        streamlit_export_lambda = self.create_streamlit_export_lambda()

        _ = self.create_update_lambda(
            knowledge_base,
            cfn_data_source,
            agent,
            agent_resource_role_arn,
        )

        self.create_streamlit_app(
            logging_context, 
            agent, 
            invoke_lambda, 
            streamlit_export_lambda
        )

    def get_config(self):

        config = dict(self.node.try_get_context("config"))

        self.ASSETS_FOLDER_NAME = config["paths"]["assets_folder_name"]
        self.KNOWLEDGEBASE_DESTINATION_PREFIX = config["paths"][
            "knowledgebase_destination_prefix"
        ]
        self.KNOWLEDGEBASE_FILE_NAME_LIST = config["paths"]["knowledgebase_file_name_list"]
        self.AGENT_SCHEMA_DESTINATION_PREFIX = config["paths"][
            "agent_schema_destination_prefix"
        ]
        self.FEWSHOT_EXAMPLES_PATH = config["paths"]["fewshot_examples_path"]
        self.LAMBDAS_SOURCE_FOLDER = config["paths"]["lambdas_source_folder"]
        self.LAYERS_SOURCE_FOLDER = config["paths"]["layers_source_folder"]
        self.VANNA_DESTINATION_PREFIX = config["paths"]["vanna_data"]

        self.BEDROCK_AGENT_NAME = config["names"]["bedrock_agent_name"]
        self.BEDROCK_AGENT_ALIAS = config["names"]["bedrock_agent_alias"]
        self.STREAMLIT_INVOKE_LAMBDA_FUNCTION_NAME = config["names"][
            "streamlit_lambda_function_name"
        ]
        self.STREAMLIT_EXPORT_LAMBDA_FUNCTION_NAME = config["names"][
            "streamlit_export_lambda_function_name"
        ]

        self.BEDROCK_AGENT_FM = config["models"]["bedrock_agent_foundation_model"]

        self.AGENT_INSTRUCTION = config["bedrock_instructions"]["agent_instruction"]
        self.ACTION_GROUP_DESCRIPTION = config["bedrock_instructions"][
            "action_group_description"
        ]
        self.KNOWLEDGEBASE_INSTRUCTION = config["bedrock_instructions"][
            "knowledgebase_instruction"
        ]
        
        self.GLUE_DATABASE = config["sources"]["glue_database"]
        self.OUTPUT_S3_BUCKET = config["sources"]["output_s3_bucket"]
        self.ATHENA_TABLE_NAME = config["sources"]["athena_table_name"]
        self.PERPLEXITY_URL = config["sources"]["perplexity_url"]
        self.SECRET_MANAGER_NAME = config["sources"]["secrets_manager_name"]
        self.SECRET_MANAGER_PPLX_NAME = config["sources"]["secrets_manager_name_pplx"]
        self.AWS_FB_MAPPING_REGION = config["sources"]["aws_fb_mapping_region"]

        self.VANNA_DOCUMENT_INDEX = config["sources"]["vanna"]["vanna_document_index"]
        self.VANNA_DDL_INDEX = config["sources"]["vanna"]["vanna_ddl_index"]
        self.VANNA_QUESTIONS_SQL_INDEX = config["sources"]["vanna"]["vanna_questions_sql_index"]
        
        return config

    def create_kms_key(self):
        # Creating new KMS key and confgiure it for S3 object encryption
        kms_key = kms.Key(
            self,
            "KMSKey",
            alias=f"alias/{self.short_stack_name}/genai-{self.unique_suffix}",
            enable_key_rotation=True,
            pending_window=Duration.days(7),
            removal_policy=RemovalPolicy.DESTROY,
        )
        kms_key.grant_encrypt_decrypt(
            iam.AnyPrincipal().with_conditions(
                {
                    "StringEquals": {
                        "kms:CallerAccount": f"{Aws.ACCOUNT_ID}",
                        "kms:ViaService": f"s3.{Aws.REGION}.amazonaws.com",
                    },
                }
            )
        )

        kms_key.grant_encrypt_decrypt(
            iam.ServicePrincipal(f"logs.{Aws.REGION}.amazonaws.com")
        )

        return kms_key

    def create_data_source_bucket(self, kms_key):
        # creating kendra source bucket
        agent_assets_bucket = s3.Bucket(
            self,
            "AgentAssetsSourceBaseBucket",
            bucket_name=f"{self.short_stack_name}-assets-{self.unique_suffix}",
            versioned=True,
            auto_delete_objects=True,
            removal_policy=RemovalPolicy.DESTROY,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=kms_key,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
        )
        NagSuppressions.add_resource_suppressions(
            agent_assets_bucket,
            suppressions=[
                {
                    "id": "AwsSolutions-S1",
                    "reason": "Demo app hence server access logs not enabled",
                }
            ],
        )
        CfnOutput(self, "AssetsBucket", value=agent_assets_bucket.bucket_name)
        return agent_assets_bucket

    def upload_files_to_s3(self, agent_assets_bucket):
        """
        knowledgebase_destination_prefix
        ├─ xxx.zip                <── 原本 single zip (若還要留著)
        ├─ 各產業報告書.zip        <── 新增
        └─ 美妝產業報告書.zip      <── 新增
        """
        for zip_name in self.KNOWLEDGEBASE_FILE_NAME_LIST:
            s3deploy.BucketDeployment(
                self,
                f"Deploy_{zip_name.replace('.', '_')}",
                sources=[
                    s3deploy.Source.asset(
                        path.join(
                            os.getcwd(),
                            self.ASSETS_FOLDER_NAME,
                            self.KNOWLEDGEBASE_DESTINATION_PREFIX,
                            zip_name,
                        )
                    )
                ],
                destination_bucket=agent_assets_bucket,
                destination_key_prefix=self.KNOWLEDGEBASE_DESTINATION_PREFIX,
                retain_on_delete=False,
                memory_limit=512
            )

        self.agent_schema_deploy = s3deploy.BucketDeployment(
            self,
            "AgentAPISchema",
            sources=[
                s3deploy.Source.asset(
                    path.join(os.getcwd(), self.ASSETS_FOLDER_NAME, "agent_api_schema")
                )
            ],
            destination_bucket=agent_assets_bucket,
            retain_on_delete=False,
            destination_key_prefix=self.AGENT_SCHEMA_DESTINATION_PREFIX,
        )

        s3deploy.BucketDeployment(
            self,
            "VannaDataDeployment",
            sources=[
                s3deploy.Source.asset(
                    path.join(os.getcwd(), self.ASSETS_FOLDER_NAME, "vanna_data")
                )
            ],
            destination_bucket=agent_assets_bucket,
            retain_on_delete=False,
            destination_key_prefix=self.VANNA_DESTINATION_PREFIX,
        )
        return

    def create_lambda_layer(self, layer_name: str) -> lambda_.LayerVersion:
        """
        Create a Lambda layer with necessary dependencies.
        Package installation is handled automatically during CDK deployment using bundling.

        Args:
            layer_name: Name of the layer and directory containing requirements.txt

        Returns:
            LayerVersion: The created Lambda layer
        """
        layer_code_path = path.join(os.getcwd(), self.LAYERS_SOURCE_FOLDER, layer_name)

        layer = lambda_.LayerVersion(
            self,
            layer_name,
            code=lambda_.Code.from_asset(
                layer_code_path,
                bundling=BundlingOptions(
                    image=DockerImage.from_registry(
                        "public.ecr.aws/sam/build-python3.12"
                    ),
                    command=[
                        "bash",
                        "-c",
                        f"""
                        # Create the required directory structure
                        mkdir -p /asset-output/python/lib/python3.12/site-packages
                        
                        # Install requirements to the correct directory
                        pip install \
                            --platform {lambda_layer_arch} \
                            --implementation cp \
                            --python-version 3.12 \
                            --only-binary=:all: \
                            --target /asset-output/python/lib/python3.12/site-packages \
                            -r requirements.txt
                        """
                    ],
                ),
            ),
            compatible_runtimes=[self.lambda_runtime],
            compatible_architectures=[compatible_arch],
            description=f"Lambda layer for {layer_name}",
            layer_version_name=f"{layer_name}-{self.unique_suffix}",
        )

        return layer

    def create_agent_executor_lambda(
        self,
        agent_assets_bucket,
        kms_key,
        logging_context,
        cfn_collection
    ):

        ecr_image = lambda_.EcrImageCode.from_asset_image(
            directory=path.join(
                os.getcwd(), self.LAMBDAS_SOURCE_FOLDER, "action-lambda"
            ),
            platform=ecr_image_platform,
        )

        # Create IAM role for Lambda function
        lambda_role = iam.Role(
            self,
            "LambdaRole",
            # 修正：缩短角色名称 (最多32字符)
            role_name=f"ActionLambda-{self.unique_suffix}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
                # Add a managed policy for AmazonBedrockFullAccess
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonBedrockFullAccess"
                ),
            ],
        )

        # Action Lambda 調用 Claude 4 所需的專用權限
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:GetInferenceProfile",  # Claude 4 跨區域訪問必需
                    "bedrock:ListInferenceProfiles",  # Claude 4 跨區域訪問必需
                    "bedrock:InvokeModel",  # 直接調用模型權限
                ],
                resources=[
                    # Foundation Models 權限（跨區域支援）
                    "arn:aws:bedrock:us-east-1::foundation-model/*",
                    "arn:aws:bedrock:us-east-2::foundation-model/*", 
                    "arn:aws:bedrock:us-west-2::foundation-model/*",
                    
                    # Inference Profiles 權限（Claude 4 跨區域訪問必需）
                    "arn:aws:bedrock:us-east-1:992382611204:inference-profile/*",
                    "arn:aws:bedrock:us-east-2:992382611204:inference-profile/*",
                    "arn:aws:bedrock:us-west-2:992382611204:inference-profile/*",
                ],
            )
        )

        # OpenSearch Serverless 和 Secrets Manager 權限
        # https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-data-access.html
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "aoss:APIAccessAll",
                    "secretsmanager:GetSecretValue", 
                    "secretsmanager:DescribeSecret"
                ],
                resources=[
                    f"arn:aws:secretsmanager:{Aws.REGION}:{Aws.ACCOUNT_ID}:secret:{self.SECRET_MANAGER_NAME}*",
                    f"arn:aws:aoss:{Aws.REGION}:{Aws.ACCOUNT_ID}:collection/{cfn_collection.attr_id}"
                ]
            )
        )

        # 加入操作 OpenSearch 所需權限
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "aoss:CreateCollection",
                    "aoss:ListCollections",
                    "aoss:BatchGetCollection",
                    "aoss:DeleteCollection",
                    "aoss:CreateAccessPolicy",
                    "aoss:ListAccessPolicies",
                    "aoss:UpdateAccessPolicy",
                    "aoss:CreateSecurityPolicy",
                    "aoss:GetSecurityPolicy",
                    "aoss:UpdateSecurityPolicy",
                    "iam:ListUsers",
                    "iam:ListRoles"
                ],
                resources=[
                    f"arn:aws:aoss:{Aws.REGION}:{Aws.ACCOUNT_ID}:collection/{cfn_collection.name}",
                    f"arn:aws:aoss:{Aws.REGION}:{Aws.ACCOUNT_ID}:index/{cfn_collection.name}/*",
                ],
            )
        )

        # OpenSearch Serverless 數據訪問策略
        opensearchserverless.CfnAccessPolicy(
            self,
            "LambdaDataAccess",
            name=f"lambda-{self.short_stack_name}-{self.unique_suffix}",
            type="data",
            policy=json.dumps([
                {
                    "Description": "Lambda can R/W all indexes in the collection",
                    "Rules": [
                        {
                            "ResourceType": "collection",
                            "Resource": [f"collection/{cfn_collection.name}"],
                            "Permission": ["aoss:*"]
                        },
                        {
                            "ResourceType": "index",
                            "Resource": [f"index/{cfn_collection.name}/*"],
                            "Permission": ["aoss:*"]
                        }
                    ],
                    "Principal": [lambda_role.role_arn]
                }
            ])
        )

        # 創建 Lambda 函數
        lambda_function = lambda_.Function(
            self,
            "AgentActionLambdaFunction",
            function_name=f"{self.short_stack_name}-action-{self.unique_suffix}",
            description="Lambda code for GenAI Chatbot",
            architecture=compatible_arch,
            handler=lambda_.Handler.FROM_IMAGE,
            runtime=lambda_.Runtime.FROM_IMAGE,
            code=ecr_image,
            environment={
                "AWS_FBMAPPING_REGION": self.AWS_FB_MAPPING_REGION,
                "OUTPUT_S3_BUCKET": self.OUTPUT_S3_BUCKET,
                "TEXT2SQL_DATABASE": self.GLUE_DATABASE,
                "LOG_LEVEL": logging_context["lambda_log_level"],
                "FEWSHOT_EXAMPLES_PATH": self.FEWSHOT_EXAMPLES_PATH,
                "SECRET_NAME": self.SECRET_MANAGER_NAME,
                "SECRET_NAME_PPLX": self.SECRET_MANAGER_PPLX_NAME,
                "ATHENA_TABLE_NAME": self.ATHENA_TABLE_NAME,
                "PREPLEXITY_URL": self.PERPLEXITY_URL,
                "OS_DOC_INDEX": self.VANNA_DOCUMENT_INDEX,
                "OS_DDL_INDEX": self.VANNA_DDL_INDEX,
                "OS_QSQL_INDEX": self.VANNA_QUESTIONS_SQL_INDEX,
                "OPENSEARCH_HOST": cfn_collection.attr_collection_endpoint
            },
            environment_encryption=kms_key,
            role=lambda_role,
            timeout=Duration.minutes(15),
            memory_size=1024,
            ephemeral_storage_size=Size.mebibytes(1024),
        )

        # 允許 Bedrock 服務調用此 Lambda 函數
        lambda_function.add_permission(
            "BedrockLambdaInvokePermission",
            principal=iam.ServicePrincipal("bedrock.amazonaws.com"),
            action="lambda:InvokeFunction",
            source_account=Aws.ACCOUNT_ID,
            source_arn=f"arn:aws:bedrock:{Aws.REGION}:{Aws.ACCOUNT_ID}:agent/*",
        )

        # 授予 S3 bucket 讀寫權限
        agent_assets_bucket.grant_read_write(lambda_role)

        return lambda_function

    def create_agent_execution_role(self, agent_assets_bucket):
        # 修正：使用唯一且短的角色名称 (最多32字符)
        role_name = f"BedrockAgent-{self.unique_suffix}"
        
        agent_resource_role = iam.Role(
            self,
            "ChatBotBedrockAgentRole",
            # 修正：角色名称不超过32字符且唯一
            role_name=role_name,
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
        )

        policy_statements = [
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeAgent",
                    "bedrock:CreateAgent",
                    "bedrock:UpdateAgent",
                    "bedrock:GetAgent",
                    "bedrock:GetInferenceProfile",
                    "bedrock:ListInferenceProfiles",
                ],
                resources=[
                    "arn:aws:bedrock:us-east-1::foundation-model/*",
                    "arn:aws:bedrock:us-east-2::foundation-model/*",
                    "arn:aws:bedrock:us-west-2::foundation-model/*",
                    "arn:aws:bedrock:us-east-1:992382611204:inference-profile/*",
                    "arn:aws:bedrock:us-east-2:992382611204:inference-profile/*",
                    "arn:aws:bedrock:us-west-2:992382611204:inference-profile/*",
                    "arn:aws:bedrock:us-east-1:992382611204:agent/*",
                    "arn:aws:bedrock:us-east-2:992382611204:agent/*",
                    "arn:aws:bedrock:us-west-2:992382611204:agent/*",
                ]
            ),
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject", "s3:ListBucket"],
                resources=[
                    f"arn:aws:s3:::{agent_assets_bucket.bucket_name}",
                    f"arn:aws:s3:::{agent_assets_bucket.bucket_name}/*",
                    "arn:aws:s3:::chatbot-stack-agent-assets-bucket-992382611204/*",
                ],
                conditions={
                    "StringEquals": {
                        "aws:ResourceAccount": Aws.ACCOUNT_ID
                    }
                }
            ),
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"],
                resources=[
                    "arn:aws:bedrock:us-east-1:992382611204:knowledge-base/*"
                ],
                conditions={
                    "StringEquals": {
                        "aws:ResourceAccount": Aws.ACCOUNT_ID
                    }
                }
            ),
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["aoss:APIAccessAll"],
                resources=[f"arn:aws:aoss:{Aws.REGION}:{Aws.ACCOUNT_ID}:collection/*"]
            ),
        ]
        for statement in policy_statements:
            agent_resource_role.add_to_policy(statement)

        return agent_resource_role

    def create_opensearch_index(self, agent_resource_role, opensearch_layer, agent_assets_bucket):
        
        vector_index_name = "bedrock-knowledgebase-index"
        vector_field_name = "bedrock-knowledge-base-default-vector"

        agent_resource_role_arn = agent_resource_role.role_arn

        create_index_lambda_execution_role = iam.Role(
            self,
            "CreateIndexExecutionRole",
            # 修正：缩短角色名称
            role_name=f"IndexRole-{self.unique_suffix}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Role for OpenSearch access",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )

        cfn_collection = opensearchserverless.CfnCollection(
            self,
            "ChatBotAgentCollection",
            name=f"{self.short_stack_name}-os-{self.unique_suffix}",
            description="ChatBot Agent Collection",
            type="VECTORSEARCH",
        )

        cfn_collection_name = cfn_collection.name

        opensearch_policy_statement = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["aoss:APIAccessAll"],
            resources=[
                f"arn:aws:aoss:{Aws.REGION}:{Aws.ACCOUNT_ID}:collection/{cfn_collection.attr_id}"
            ],
        )

        # Attach the custom policy to the role
        create_index_lambda_execution_role.add_to_policy(opensearch_policy_statement)

        # get the role arn
        create_index_lambda_execution_role_arn = (
            create_index_lambda_execution_role.role_arn
        )

        agent_resource_role.add_to_policy(opensearch_policy_statement)

        policy_json = {
            "Rules": [
                {
                    "ResourceType": "collection",
                    "Resource": [f"collection/{cfn_collection_name}"],
                }
            ],
            "AWSOwnedKey": True,
        }

        json_dump = json.dumps(policy_json)

        encryption_policy = CfnResource(
            self,
            "EncryptionPolicy",
            type="AWS::OpenSearchServerless::SecurityPolicy",
            properties={
                "Name": f"{self.short_stack_name}-enc-{self.unique_suffix}",
                "Type": "encryption",
                "Description": "Encryption policy for Bedrock collection.",
                "Policy": json_dump,
            },
        )

        policy_json = [
            {
                "Rules": [
                    {
                        "ResourceType": "collection",
                        "Resource": [f"collection/{cfn_collection_name}"],
                    },
                    {
                        "ResourceType": "dashboard",
                        "Resource": [f"collection/{cfn_collection_name}"],
                    },
                ],
                "AllowFromPublic": True,
            }
        ]
        json_dump = json.dumps(policy_json)

        network_policy = CfnResource(
            self,
            "NetworkPolicy",
            type="AWS::OpenSearchServerless::SecurityPolicy",
            properties={
                "Name": f"{self.short_stack_name}-net-{self.unique_suffix}",
                "Type": "network",
                "Description": "Network policy for Bedrock collection",
                "Policy": json_dump,
            },
        )

        policy_json = [
            {
                "Description": "Access for cfn user",
                "Rules": [
                    {
                        "ResourceType": "index",
                        "Resource": ["index/*/*"],
                        "Permission": ["aoss:*"],
                    },
                    {
                        "ResourceType": "collection",
                        "Resource": [f"collection/{cfn_collection_name}"],
                        "Permission": ["aoss:*"],
                    },
                ],
                "Principal": [
                    agent_resource_role_arn,
                    create_index_lambda_execution_role_arn,
                    f"arn:aws:iam::{Aws.ACCOUNT_ID}:root"
                ],
            }
        ]

        json_dump = json.dumps(policy_json)

        data_policy = CfnResource(
            self,
            "DataPolicy",
            type="AWS::OpenSearchServerless::AccessPolicy",
            properties={
                "Name": f"{self.short_stack_name}-data-{self.unique_suffix}",
                "Type": "data",
                "Description": "Data policy for Bedrock collection.",
                "Policy": json_dump,
            },
        )

        cfn_collection.add_dependency(network_policy)
        cfn_collection.add_dependency(encryption_policy)
        cfn_collection.add_dependency(data_policy)

        self.create_index_lambda = lambda_.Function(
            self,
            "CreateIndexLambda",
            function_name=f"{self.short_stack_name}-index-{self.unique_suffix}",
            runtime=self.lambda_runtime,
            handler="index.lambda_handler",
            code=lambda_.Code.from_asset(
                path.join(
                    os.getcwd(), self.LAMBDAS_SOURCE_FOLDER, "create-index-lambda"
                )
            ),
            layers=[opensearch_layer],
            architecture=compatible_arch,
            environment={
                "REGION_NAME": Aws.REGION,
                "COLLECTION_HOST": cfn_collection.attr_collection_endpoint,
                "VECTOR_INDEX_NAME": vector_index_name,
                "VECTOR_FIELD_NAME": vector_field_name,
                "DOCUMENT_INDEX": self.VANNA_DOCUMENT_INDEX,
                "DDL_INDEX": self.VANNA_DDL_INDEX, 
                "QUESTION_SQL_INDEX": self.VANNA_QUESTIONS_SQL_INDEX
            },
            role=create_index_lambda_execution_role,
            timeout=Duration.minutes(15),
            tracing=lambda_.Tracing.ACTIVE,
        )

        lambda_provider = cr.Provider(
            self,
            "LambdaCreateIndexCustomProvider",
            on_event_handler=self.create_index_lambda,
        )

        lambda_cr = CustomResource(
            self,
            "LambdaCreateIndexCustomResource",
            service_token=lambda_provider.service_token,
        )

        _ = self.create_vanna_data_init_lambda(
            agent_assets_bucket, 
            opensearch_layer, 
            cfn_collection, 
            create_index_lambda_execution_role,
            lambda_cr
        )
        
        return (
            cfn_collection,
            vector_field_name,
            vector_index_name,
            lambda_cr,
        )

    def create_knowledgebase(
        self,
        vector_field_name,
        vector_index_name,
        cfn_collection,
        agent_resource_role,
        lambda_cr,
    ):

        kb_name = f"KB-{self.short_stack_name}-{self.unique_suffix}"
        text_field = "AMAZON_BEDROCK_TEXT_CHUNK"
        metadata_field = "AMAZON_BEDROCK_METADATA"
        agent_resource_role_arn = agent_resource_role.role_arn

        # mid = bedrock.FoundationModelIdentifier("amazon.titan-embed-text-v2:0")

        embed_moodel = bedrock.FoundationModel.from_foundation_model_id(
            self,
            "embedding_model",
            bedrock.FoundationModelIdentifier.AMAZON_TITAN_EMBED_G1_TEXT_02,
        )
        cfn_knowledge_base = "cfn_knowledge_base"

        cfn_knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            "BedrockOpenSearchKnowledgeBase",
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=embed_moodel.model_arn
                ),
            ),
            name=kb_name,
            role_arn=agent_resource_role_arn,
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="OPENSEARCH_SERVERLESS",
                # the properties below are optional
                opensearch_serverless_configuration=bedrock.CfnKnowledgeBase.OpenSearchServerlessConfigurationProperty(
                    collection_arn=cfn_collection.attr_arn,
                    field_mapping=bedrock.CfnKnowledgeBase.OpenSearchServerlessFieldMappingProperty(
                        metadata_field=metadata_field,
                        text_field=text_field,
                        vector_field=vector_field_name,
                    ),
                    vector_index_name=vector_index_name,
                ),
            ),
            description="Use this prompt to return descriptive, structured industry insights and strategy recommendations directly from internal knowledge bases. Use it to answer qualitative or guidance-based questions.",
        )

        for child in lambda_cr.node.children:
            if isinstance(child, CustomResource):
                break

        cfn_knowledge_base.add_dependency(child)

        return cfn_knowledge_base, agent_resource_role_arn

    def create_agent_data_source(self, knowledge_base, agent_assets_bucket):
        """
        Bedrock ingestion job 背後會做:
        1. 解壓縮 .zip 檔
        2. 掃出 .pdf, .docx, .html, .txt, .md, .csv 等格式
        3. 將裡面的內容：
            - 分段 (chunking)
            - 建立向量
            - 上傳到 OpenSearch Serverless
        """
        data_source_bucket_arn = f"arn:aws:s3:::{agent_assets_bucket.bucket_name}"

        cfn_data_source = bedrock.CfnDataSource(
            self,
            "BedrockKnowledgeBaseSource",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=data_source_bucket_arn,
                    # the properties below are optional
                    bucket_owner_account_id=Aws.ACCOUNT_ID,
                    inclusion_prefixes=[f"{self.KNOWLEDGEBASE_DESTINATION_PREFIX}/"],
                ),
                type="S3",
            ),
            knowledge_base_id=knowledge_base.attr_knowledge_base_id,
            name="BedrockKnowledgeBaseSource",
            # the properties below are optional
            data_deletion_policy="RETAIN",
            description="description",
        )

        return cfn_data_source

    def create_bedrock_agent(
        self,
        agent_executor_lambda,
        agent_assets_bucket,
        agent_resource_role,
        cfn_knowledge_base,
    ):
        agent_resource_role_arn = agent_resource_role.role_arn
        s3_bucket_name = agent_assets_bucket.bucket_name
        s3_object_key = f"{self.AGENT_SCHEMA_DESTINATION_PREFIX}/artifacts_schema.json"

        cfn_agent = bedrock.CfnAgent(
            self,
            "ChatbotBedrockAgent",
            agent_name=f"{self.BEDROCK_AGENT_NAME}-{self.unique_suffix}",
            # the properties below are optional
            action_groups=[
                bedrock.CfnAgent.AgentActionGroupProperty(
                    action_group_name="ChatBotBedrockAgentActionGroup",
                    # the properties below are optional
                    action_group_executor=bedrock.CfnAgent.ActionGroupExecutorProperty(
                        lambda_=agent_executor_lambda.function_arn
                    ),
                    ## action_group_state="actionGroupState",
                    api_schema=bedrock.CfnAgent.APISchemaProperty(
                        # payload="payload",
                        s3=bedrock.CfnAgent.S3IdentifierProperty(
                            s3_bucket_name=s3_bucket_name, s3_object_key=s3_object_key
                        ),
                    ),
                    description=self.ACTION_GROUP_DESCRIPTION,
                    ## parent_action_group_signature="parentActionGroupSignature",
                    ## skip_resource_in_use_check_on_delete=False,
                )
            ],
            agent_resource_role_arn=agent_resource_role_arn,
            description="Bedrock Chatbot Agent",
            foundation_model=self.BEDROCK_AGENT_FM,
            idle_session_ttl_in_seconds=3600,
            instruction=self.AGENT_INSTRUCTION,
            knowledge_bases=[
                bedrock.CfnAgent.AgentKnowledgeBaseProperty(
                    description=cfn_knowledge_base.description,
                    knowledge_base_id=cfn_knowledge_base.attr_knowledge_base_id,
                )
            ],
            # prompt_override_configuration=bedrock.CfnAgent.PromptOverrideConfigurationProperty(
            #     # 行為引導腳本 —— Agent 在這三個階段，會根據你的模板內容來決定下一步邏輯
            #     prompt_configurations=[
            #         bedrock.CfnAgent.PromptConfigurationProperty(
            #             base_prompt_template=PREPROCESSING_TEMPLATE,
            #             inference_configuration=bedrock.CfnAgent.InferenceConfigurationProperty(
            #                 maximum_length=256,
            #                 stop_sequences=["\n\nHuman:"],
            #                 temperature=0,
            #                 top_k=250,
            #                 top_p=1,
            #             ),
            #             parser_mode="DEFAULT",
            #             prompt_creation_mode="OVERRIDDEN",
            #             prompt_state="ENABLED",
            #             prompt_type="PRE_PROCESSING",
            #         ),
            #         bedrock.CfnAgent.PromptConfigurationProperty(
            #             base_prompt_template=ORCHESTRATION_TEMPLATE,
            #             inference_configuration=bedrock.CfnAgent.InferenceConfigurationProperty(
            #                 maximum_length=2048,
            #                 stop_sequences=["</function_call>", "</answer>", "/error"],
            #                 temperature=0,
            #                 top_k=250,
            #                 top_p=1,
            #             ),
            #             parser_mode="DEFAULT",
            #             prompt_creation_mode="OVERRIDDEN",
            #             prompt_state="ENABLED",
            #             prompt_type="ORCHESTRATION",
            #         ),
            #         bedrock.CfnAgent.PromptConfigurationProperty(
            #             base_prompt_template=ORCHESTRATION_TEMPLATE,
            #             inference_configuration=bedrock.CfnAgent.InferenceConfigurationProperty(
            #                 maximum_length=2048,
            #                 stop_sequences=["\n\nHuman:"],
            #                 temperature=0,
            #                 top_k=250,
            #                 top_p=1,
            #             ),
            #             parser_mode="DEFAULT",
            #             prompt_creation_mode="OVERRIDDEN",
            #             prompt_state="ENABLED",
            #             prompt_type="KNOWLEDGE_BASE_RESPONSE_GENERATION",
            #         ),
            #     ]
            # ),
        )

        cfn_agent.node.add_dependency(self.agent_schema_deploy)

        return cfn_agent

    # 主要功能: 使用者輸入
    def create_bedrock_agent_invoke_lambda(self, agent, agent_assets_bucket):
        
        invoke_lambda_role = iam.Role(
            self,
            "InvokeLambdaExecutionRole",
            # 修正：缩短角色名称
            role_name=f"InvokeLambda-{self.unique_suffix}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Role for Lambda to access Bedrock agents and S3",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )

        # 完整的 Bedrock agent 權限（支援 Claude 4）
        invoke_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:ListAgents",
                    "bedrock:ListAgentAliases",
                    "bedrock:InvokeAgent",
                    "bedrock:InvokeModel",  # 新增：調用模型權限
                    "bedrock:CreateAgent",  # 新增：代理管理權限
                    "bedrock:UpdateAgent",  # 新增：代理更新權限
                    "bedrock:GetAgent",  # 新增：獲取代理權限
                    "bedrock:GetInferenceProfile",  # Claude 4 需要的權限
                    "bedrock:ListInferenceProfiles"  # Claude 4 需要的權限
                ],
                resources=[
                    f"arn:aws:bedrock:{Aws.REGION}:{Aws.ACCOUNT_ID}:agent/{agent.attr_agent_id}",
                    f"arn:aws:bedrock:{Aws.REGION}:{Aws.ACCOUNT_ID}:agent-alias/{agent.attr_agent_id}/*",
                    
                    # Foundation Models 權限（跨區域支援）
                    "arn:aws:bedrock:us-east-1::foundation-model/*",
                    "arn:aws:bedrock:us-east-2::foundation-model/*", 
                    "arn:aws:bedrock:us-west-2::foundation-model/*",
                    
                    # Inference Profiles 權限（Claude 4 跨區域訪問必需）
                    "arn:aws:bedrock:us-east-1:992382611204:inference-profile/*",
                    "arn:aws:bedrock:us-east-2:992382611204:inference-profile/*",
                    "arn:aws:bedrock:us-west-2:992382611204:inference-profile/*",
                    
                    # Agent 相關權限（完整支援）
                    "arn:aws:bedrock:us-east-1:992382611204:agent/*",
                    "arn:aws:bedrock:us-east-2:992382611204:agent/*",
                    "arn:aws:bedrock:us-west-2:992382611204:agent/*",
                ],
            )
        )

        # S3 permissions
        invoke_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject", "s3:ListBucket"],
                resources=[
                    f"arn:aws:s3:::{agent_assets_bucket.bucket_name}",
                    f"arn:aws:s3:::{agent_assets_bucket.bucket_name}/*",
                ],
            )
        )

        invoke_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:DescribeSecret"
                ],
                resources=[
                    f"arn:aws:secretsmanager:{Aws.REGION}:{Aws.ACCOUNT_ID}:secret:{self.SECRET_MANAGER_NAME}-*",
                    f"arn:aws:secretsmanager:{self.AWS_FB_MAPPING_REGION}:{Aws.ACCOUNT_ID}:secret:{self.SECRET_MANAGER_NAME}-*",
                ],
                effect=iam.Effect.ALLOW,
            )
        )
        
        self.invoke_lambda = lambda_.DockerImageFunction(
            self,
            self.STREAMLIT_INVOKE_LAMBDA_FUNCTION_NAME,
            function_name=f"{self.short_stack_name}-invoke-{self.unique_suffix}",
            code=lambda_.DockerImageCode.from_image_asset(
                directory=path.join(os.getcwd(), self.LAMBDAS_SOURCE_FOLDER, "invoke-lambda"),
                platform=ecr_image_platform
            ),
            role=invoke_lambda_role,
            environment={
                "AGENT_ID": agent.attr_agent_id,
                "REGION_NAME": Aws.REGION,
                "AWS_FBMAPPING_REGION": self.AWS_FB_MAPPING_REGION,  # 取出S3圖片
                "SECRET_NAME": self.SECRET_MANAGER_NAME,  # 取出S3圖片
            },
            timeout=Duration.minutes(15),
            tracing=lambda_.Tracing.ACTIVE,
            memory_size=512,  # 512MB , 0.5 vCPU
        )
        CfnOutput(
            self,
            "StreamlitInvokeLambdaFunction",
            value=self.invoke_lambda.function_name,
        )

        return self.invoke_lambda
    
    # 主要功能: 匯出檔案
    def create_streamlit_export_lambda(self):
        export_lambda_role = iam.Role(
            self,
            "ExportLambdaExecutionRole",
            # 修正：缩短角色名称
            role_name=f"ExportLambda-{self.unique_suffix}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Role for Lambda to access S3",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )
        export_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
                resources=[
                    f"arn:aws:secretsmanager:{Aws.REGION}:{Aws.ACCOUNT_ID}:secret:{self.SECRET_MANAGER_NAME}*"
                ]
            )
        )

        # Bedrock agent permissions
        export_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject", "s3:ListBucket", "s3:PutObject"],
                resources=[
                    f"arn:aws:s3:::{self.OUTPUT_S3_BUCKET}",
                    f"arn:aws:s3:::{self.OUTPUT_S3_BUCKET}/*",
                ],
            )
        )

        export_lambda_image = lambda_.EcrImageCode.from_asset_image(
            directory=path.join(os.getcwd(), self.LAMBDAS_SOURCE_FOLDER, "export-lambda"),
            platform=ecr_image_platform,
        )

        self.export_lambda = lambda_.Function(
            self,
            self.STREAMLIT_EXPORT_LAMBDA_FUNCTION_NAME,
            function_name=f"{self.short_stack_name}-export-{self.unique_suffix}",
            architecture=compatible_arch,
            handler=lambda_.Handler.FROM_IMAGE,
            runtime=lambda_.Runtime.FROM_IMAGE,
            code=export_lambda_image,
            environment={
                "OUTPUT_S3_BUCKET": self.OUTPUT_S3_BUCKET,
                "SECRET_NAME": self.SECRET_MANAGER_NAME
            },
            role=export_lambda_role,
            timeout=Duration.minutes(15),
            tracing=lambda_.Tracing.ACTIVE,
        )

        CfnOutput(
            self,
            "StreamlitExportLambdaFunction",
            value=self.export_lambda.function_name,
        )

        return self.export_lambda

    def create_vanna_data_init_lambda(
            self,
            agent_assets_bucket, 
            opensearch_layer, 
            cfn_collection, 
            create_index_lambda_execution_role, 
            lambda_cr
    ):
        """創建設定 Vanna 數據初始化 Lambda 函數"""
        
        # 確保 Lambda 有權限訪問 S3
        create_index_lambda_execution_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject", "s3:ListBucket"],
                resources=[
                    f"arn:aws:s3:::{agent_assets_bucket.bucket_name}",
                    f"arn:aws:s3:::{agent_assets_bucket.bucket_name}/*",
                ],
            )
        )
        
        # 創建 Lambda 函數
        vanna_data_init_lambda = lambda_.Function(
            self,
            "VannaDataInitLambda",
            function_name=f"{self.short_stack_name}-vanna-{self.unique_suffix}",
            runtime=self.lambda_runtime,
            handler="index.lambda_handler",
            code=lambda_.Code.from_asset(
                path.join(
                    os.getcwd(), self.LAMBDAS_SOURCE_FOLDER, "vanna-init-data-lambda"
                )
            ),
            layers=[opensearch_layer],
            architecture=compatible_arch,
            environment={
                "REGION_NAME": Aws.REGION,
                "COLLECTION_HOST": cfn_collection.attr_collection_endpoint,
                "S3_BUCKET": agent_assets_bucket.bucket_name,
                "DOCUMENT_INDEX": self.VANNA_DOCUMENT_INDEX,
                "DDL_INDEX": self.VANNA_DDL_INDEX, 
                "QUESTION_SQL_INDEX": self.VANNA_QUESTIONS_SQL_INDEX
            },
            role=create_index_lambda_execution_role,
            timeout=Duration.minutes(15),
            tracing=lambda_.Tracing.ACTIVE,
        )
        
        # 創建 Lambda 提供者和 CustomResource
        vanna_data_provider = cr.Provider(
            self,
            "VannaDataInitProvider",
            on_event_handler=vanna_data_init_lambda,
        )
        
        vanna_data_cr = CustomResource(
            self,
            "VannaDataInitResource",
            service_token=vanna_data_provider.service_token,
            # properties={
            #     "version": "2"  # 測試用
            # }
        )
        
        # 確保在索引創建後再上傳數據
        vanna_data_cr.node.add_dependency(lambda_cr)
        
        return vanna_data_cr

    def create_update_lambda(
        self,
        knowledge_base,
        cfn_data_source,
        bedrock_agent,
        agent_resource_role_arn,
    ):

        # Create IAM role for the update lambda
        lambda_role = iam.Role(
            self,
            "LambdaRole_update_resources",
            # 修正：缩短角色名称
            role_name=f"UpdateLambda-{self.unique_suffix}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSGlueServiceRole"
                ),
            ],
        )

        # Define the policy statement
        bedrock_policy_statement = iam.PolicyStatement(
            actions=[
                "bedrock:StartIngestionJob",
                "bedrock:UpdateAgentKnowledgeBase",
                "bedrock:GetAgentAlias",
                "bedrock:UpdateKnowledgeBase",
                "bedrock:UpdateAgent",
                "bedrock:GetIngestionJob",
                "bedrock:CreateAgentAlias",
                "bedrock:UpdateAgentAlias",
                "bedrock:GetAgent",
                "bedrock:PrepareAgent",
                "bedrock:DeleteAgentAlias",
                "bedrock:DeleteAgent",
                "bedrock:ListAgentAliases",
            ],
            resources=[
                f"arn:aws:bedrock:{Aws.REGION}:{Aws.ACCOUNT_ID}:agent/*",
                f"arn:aws:bedrock:{Aws.REGION}:{Aws.ACCOUNT_ID}:agent-alias/*",
                f"arn:aws:bedrock:{Aws.REGION}:{Aws.ACCOUNT_ID}:knowledge-base/*",
            ],
            effect=iam.Effect.ALLOW,
        )

        # Create the policy
        update_agent_kb_policy = iam.Policy(
            self,
            "BedrockAgent_KB_Update_Policy",
            policy_name="allow_update_agent_kb_policy",
            statements=[bedrock_policy_statement],
        )

        lambda_role.attach_inline_policy(update_agent_kb_policy)

        # create lambda function to trigger crawler, create bedrock agent alias, knowledgebase data sync
        lambda_function_update = lambda_.Function(
            self,
            "LambdaFunction_update_resources",
            function_name=f"{self.short_stack_name}-update-{self.unique_suffix}",
            description="Lambda code to trigger crawler, create bedrock agent alias, knowledgebase data sync",
            architecture=compatible_arch,
            handler="lambda_handler.lambda_handler",
            runtime=self.lambda_runtime,
            code=lambda_.Code.from_asset(
                path.join(os.getcwd(), self.LAMBDAS_SOURCE_FOLDER, "update-lambda")
            ),
            environment={
                "KNOWLEDGEBASE_ID": knowledge_base.attr_knowledge_base_id,
                "KNOWLEDGEBASE_DATASOURCE_ID": cfn_data_source.attr_data_source_id,
                "BEDROCK_AGENT_ID": bedrock_agent.attr_agent_id,
                "BEDROCK_AGENT_NAME": self.BEDROCK_AGENT_NAME,
                "BEDROCK_AGENT_ALIAS": self.BEDROCK_AGENT_ALIAS,
                "BEDROCK_AGENT_RESOURCE_ROLE_ARN": agent_resource_role_arn,
                "LOG_LEVEL": "info",
            },
            role=lambda_role,
            timeout=Duration.minutes(15),
            memory_size=1024,
        )

        lambda_provider = cr.Provider(
            self,
            "LambdaUpdateResourcesCustomProvider",
            on_event_handler=lambda_function_update,
        )

        _ = CustomResource(
            self,
            "LambdaUpdateResourcesCustomResource",
            service_token=lambda_provider.service_token,
        )

        return lambda_function_update

    def create_streamlit_app(
            self, 
            logging_context, 
            agent, 
            invoke_lambda, 
            streamlit_export_lambda
    ):
        # 創建 VPC
        vpc = ec2.Vpc(
            self, "ChatBotDemoVPC", max_azs=2, vpc_name=f"{self.short_stack_name}-vpc"
        )
        NagSuppressions.add_resource_suppressions(
            vpc,
            suppressions=[
                {"id": "AwsSolutions-VPC7", "reason": "VPC used for hosting demo app"}
            ],
        )

        # 創建 ECS cluster
        cluster = ecs.Cluster(
            self,
            "ChatBotDemoCluster",
            cluster_name=f"{self.short_stack_name}-ecs-cluster",
            container_insights=True,
            vpc=vpc,
        )

        # 從本地建構 image 並推向 ECR
        image = ecs.ContainerImage.from_asset(
            path.join(os.getcwd(), "code", "streamlit-app"),
            platform=Platform.LINUX_AMD64,
        )

        # 優化後的 Fargate service 配置
        fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "ChatBotService",
            cluster=cluster,

            # 起始實例：從 1 → 2 (提高可用性)
            # 理由：避免冷啟動，確保用戶體驗
            desired_count=2,  # 2個實例提供高可用性
            
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=image,
                container_port=8501,
                
                # 優化環境變數
                environment={
                    "LAMBDA_FUNCTION_NAME": invoke_lambda.function_name,
                    "EXPORT_LAMBDA_FUNCTION_NAME": streamlit_export_lambda.function_name,
                    "LOG_LEVEL": logging_context["streamlit_log_level"],
                    "AGENT_ID": agent.attr_agent_id,
                    
                    # 最大化 Streamlit 配置
                    "STREAMLIT_SERVER_MAX_UPLOAD_SIZE": "1000",  # 1GB 上傳限制
                    "STREAMLIT_SERVER_MAX_MESSAGE_SIZE": "1000",  # 1GB 消息限制  
                    "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
                    "STREAMLIT_SERVER_ENABLE_CORS": "false",
                    "STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION": "true",
                    
                    # Python 和系統優化
                    "PYTHONUNBUFFERED": "1",
                    "PYTHONASYNCIODEBUG": "0",
                    "PYTHONOPTIMIZE": "2",  # 最高 Python 優化級別
                    "MALLOC_ARENA_MAX": "2",  # 限制記憶體 arena 數量
                    "PYTHONHASHSEED": "0",  # 穩定的 hash seed
                    
                    # 網路和超時優化
                    "AWS_MAX_ATTEMPTS": "2",
                    "AWS_RETRY_MODE": "adaptive",
                    "STREAMLIT_SERVER_CONNECTION_TIMEOUT": "3600",  # 1小時連接超時
                    "STREAMLIT_SERVER_FILE_WATCHER_TYPE": "none",   # 禁用文件監控
                },
                
                # 容器日誌配置
                log_driver=ecs.LogDriver.aws_logs(
                    stream_prefix="streamlit-app",
                    log_retention=logs.RetentionDays.THREE_DAYS,  # 7天日誌保留
                ),
            ),
            
            service_name=f"{self.short_stack_name}-chatbot-service",
            
            # 記憶體優化：保持 4096 MiB
            # 理由：需要暫存用戶 session 和處理大型 HTML 響應
            cpu=4096,  # 1 vCPU，足夠處理 UI 和 session 管理
            memory_limit_mib=30720,  # 4GB 記憶體 (保持不變，用於 session 管理)
            # idle_timeout=Duration.seconds(400),  # 400秒閒置超時 (需調整)
            
            public_load_balancer=True,
            platform_version=ecs.FargatePlatformVersion.LATEST,
            runtime_platform=ecs.RuntimePlatform(
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
                #cpu_architecture=compatible_ecs_arch
                cpu_architecture=ecs.CpuArchitecture.X86_64
            ),
            
            # 健康檢查優化
            health_check_grace_period=Duration.seconds(300),  # 2分鐘啟動時間
        )

        # 智能化 Auto Scaling 配置
        scaling = fargate_service.service.auto_scale_task_count(
            # 📈 最大容量：從 3 → 5 (處理流量突增) 
            max_capacity=10,  # 最多5個實例
            min_capacity=3,  # 最少2個實例 (高可用性)
        )
        
        # CPU-based scaling (主要指標)
        scaling.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=50,  # 50% CPU 觸發擴展
            scale_in_cooldown=Duration.minutes(10),   # 10分鐘冷卻 (避免頻繁縮減)
            scale_out_cooldown=Duration.minutes(1),  # 1分鐘冷卻 (快速響應)
        )
        
        # Memory-based scaling (輔助指標)
        scaling.scale_on_memory_utilization(
            "MemoryScaling", 
            target_utilization_percent=60,  # 60% 記憶體觸發擴展
            scale_in_cooldown=Duration.minutes(10),
            scale_out_cooldown=Duration.minutes(1),
        )
        
        # Request-based scaling (用戶體驗導向)
        scaling.scale_on_request_count(
            "RequestCountScaling",
            requests_per_target=50,  # 每個實例最多50個併發請求
            target_group=fargate_service.target_group,
            scale_in_cooldown=Duration.minutes(10),
            scale_out_cooldown=Duration.minutes(1),  # 1分鐘快速響應
        )

        # Load Balancer 優化
        fargate_service.load_balancer.set_attribute(
            key="idle_timeout.timeout_seconds",
            value="3600"  # 1小時 idle timeout
        )

        # 安全性和權限優化 (保持原有邏輯)
        NagSuppressions.add_resource_suppressions(
            fargate_service,
            suppressions=[
                {"id": "AwsSolutions-ELB2", "reason": "LB used for hosting demo app"}
            ],
            apply_to_children=True,
        )
        NagSuppressions.add_resource_suppressions(
            fargate_service,
            suppressions=[
                {
                    "id": "AwsSolutions-EC23",
                    "reason": "Enabling Chatbot access in HTTP port",
                }
            ],
            apply_to_children=True,
        )
        NagSuppressions.add_resource_suppressions(
            fargate_service,
            suppressions=[
                {
                    "id": "AwsSolutions-ECS2",
                    "reason": "Environment variables needed for accessing lambda",
                }
            ],
            apply_to_children=True,
        )

        # 加入 policies 到 task role
        invoke_lambda.grant_invoke(fargate_service.task_definition.task_role)
        streamlit_export_lambda.grant_invoke(fargate_service.task_definition.task_role)
        
        # # 📊 CloudWatch 監控和警報
        # # CPU 使用率警報
        # cpu_alarm = cloudwatch.Alarm(
        #     self, "HighCPUAlarm",
        #     alarm_description="ECS service high CPU utilization",
        #     metric=fargate_service.service.metric_cpu_utilization(),
        #     threshold=80,
        #     evaluation_periods=2,
        #     period=Duration.minutes(5),
        # )
        
        # # 記憶體使用率警報  
        # memory_alarm = cloudwatch.Alarm(
        #     self, "HighMemoryAlarm",
        #     alarm_description="ECS service high memory utilization", 
        #     metric=fargate_service.service.metric_memory_utilization(),
        #     threshold=85,
        #     evaluation_periods=2,
        #     period=Duration.minutes(5),
        # )
        
        # # 🏷️ 成本追蹤標籤
        # Tags.of(fargate_service).add("Project", "StreamlitChatbot")
        # Tags.of(fargate_service).add("Environment", "Production")
        # Tags.of(fargate_service).add("CostCenter", "AI-Analytics")
        
        return fargate_service