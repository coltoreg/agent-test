from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth
import boto3
import os
import json
import logging
import cfnresponse
import uuid

COLLECTION_HOST = os.environ.get('COLLECTION_HOST')
REGION_NAME = os.environ.get('REGION_NAME')
S3_BUCKET = os.environ.get('S3_BUCKET')
DOCUMENT_INDEX = os.environ.get('DOCUMENT_INDEX')
DDL_INDEX = os.environ.get('DDL_INDEX')
QUESTION_SQL_INDEX = os.environ.get('QUESTION_SQL_INDEX')
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def log(message):
    logger.info(message)

def lambda_handler(event, context):
    """
    Lambda handler to load data from S3 to OpenSearch indices
    """
    log(f"Event: {json.dumps(event)}")

    session = boto3.Session()
    creds = session.get_credentials()
    s3_client = boto3.client('s3')

    host = COLLECTION_HOST.split("//")[1]
    region = REGION_NAME
    service = "aoss"
    status = cfnresponse.SUCCESS
    response_data = {}

    try:

        # 創建 opensearch 客戶端
        auth = AWSV4SignerAuth(creds, region, service)
        client = OpenSearch(
            hosts=[{"host": host, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            pool_maxsize=20,
        )

        if event["RequestType"] == "Create":
            log("Starting data initialization for Vanna indices")
            
            # 加載文檔數據
            try:
                log(f"Loading document data from S3://{S3_BUCKET}/vanna_data/documents.json")
                response = s3_client.get_object(Bucket=S3_BUCKET, Key="vanna_data/documents.json")
                docs = json.loads(response['Body'].read().decode('utf-8'))
                
                for doc in docs:
                    client.index(index=DOCUMENT_INDEX, body={"doc": doc})
                log(f"Successfully loaded {len(docs)} documents")
            except Exception as e:
                log(f"Error loading documents: {str(e)}")
            
            # 加載 DDL 數據
            try:
                log(f"Loading DDL data from S3://{S3_BUCKET}/vanna_data/ddl.json")
                response = s3_client.get_object(Bucket=S3_BUCKET, Key="vanna_data/ddl.json")
                ddls = json.loads(response['Body'].read().decode('utf-8'))
                
                for ddl in ddls:
                    client.index(index=DDL_INDEX, body={"ddl": ddl})
                log(f"Successfully loaded {len(ddls)} DDL statements")
            except Exception as e:
                log(f"Error loading DDL statements: {str(e)}")
            
            # 加載 問題/SQL 數據
            try:
                log(f"Loading Question/SQL data from S3://{S3_BUCKET}/vanna_data/questions_sql.json")
                response = s3_client.get_object(Bucket=S3_BUCKET, Key="vanna_data/questions_sql.json")
                questions = json.loads(response['Body'].read().decode('utf-8'))
                
                for item in questions:
                    client.index(index=QUESTION_SQL_INDEX, body={
                        "question": item["question"],
                        "sql": item["sql"]
                    })
                log(f"Successfully loaded {len(questions)} question/SQL pairs")
            except Exception as e:
                log(f"Error loading question/SQL pairs: {str(e)}")
            
            response_data = {"message": "Data initialization completed"}
        
        elif event["RequestType"] == "Update":
            log("Update request - no action taken")
            response_data = {"message": "No action for update"}
        
        elif event["RequestType"] == "Delete":
            log("Delete request - no specific data cleanup needed")
            response_data = {"message": "No specific cleanup needed"}

    except Exception as e:
        log(f"Error in Lambda function: {str(e)}")
        status = cfnresponse.FAILED
        response_data = {"error": str(e)}

    finally:
        cfnresponse.send(event, context, status, response_data)

    return {
        "statusCode": 200,
        "body": json.dumps("Vanna data initialization completed")
    }