from trigger_glue_crawler import trigger_glue_crawler
from trigger_data_source_sync import trigger_data_source_sync
from prepare_agent import prepare_bedrock_agent
from create_agent_alias import create_bedrock_agent_alias
from connections import Connections
import cfnresponse
import botocore.exceptions

import logging

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

glue_client = Connections.glue_client
bedrock_agent = Connections.bedrock_agent
agent_id = Connections.agent_id
agent_alias_name = Connections.agent_alias_name
agent_name = Connections.agent_name
agent_resource_role_arn = Connections.agent_resource_role_arn
data_source_id = Connections.data_source_id
knowledgebase_id = Connections.knowledgebase_id
crawler_name = Connections.crawler_name
update_agent = Connections.update_agent


def lambda_handler(event, context):
    """
    Trigger Glue Crawler, Data Source Sync, Create Agent Alias, and Update Agent Prompts (optional).
    """
    logger.info(f"Received event: {event}")

    status = cfnresponse.SUCCESS
    status_code = 200
    status_body = "Success"
    response = {}

    # Special handling for DELETE operations - always return SUCCESS
    is_delete_operation = event.get("RequestType") == "Delete"

    try:
        if event["RequestType"] == "Create":
            
            # Trigger Glue Crawler
            if crawler_name:
                logger.info("Starting Glue Crawler trigger.")
                trigger_glue_crawler(glue_client, crawler_name)
                logger.info("Glue Crawler triggered successfully.")
            else:
                logger.info("GLUE_CRAWLER_NAME not set, skipping crawler trigger.")

            # Trigger Data Source Sync
            logger.info("Starting Data Source Sync.")
            trigger_data_source_sync(bedrock_agent, knowledgebase_id, data_source_id)
            logger.info("Data Source Sync triggered successfully.")

            # Preapre Bedrock Agent
            logger.info("Starting Preparing Bedrock Agent.")
            prepare_bedrock_agent(bedrock_agent, agent_id)
            logger.info("Bedrock Agent Prepared successfully.")

            # Create Agent Alias
            logger.info("Creating Agent Alias.")
            create_bedrock_agent_alias(bedrock_agent, agent_id, agent_alias_name)
            logger.info("Agent Alias created successfully.")

        elif event["RequestType"] == "Delete":
            # Enhanced Delete operation with better error handling
            delete_errors = []
            
            try:
                # Try to list aliases with error handling
                try:
                    response = bedrock_agent.list_agent_aliases(agentId=agent_id)
                    alias_ids = [
                        summary["agentAliasId"] for summary in response["agentAliasSummaries"]
                    ]
                    logger.info(f"Deleting alias ids: {alias_ids}.")

                    # Process each alias with individual error handling
                    for agent_alias_id in alias_ids:
                        try:
                            # Skip problematic alias ID
                            if agent_alias_id == "TSTALIASID":
                                logger.warning(f"Skipping known problematic alias ID: {agent_alias_id}")
                                continue
                                
                            bedrock_agent.delete_agent_alias(
                                agentId=agent_id, agentAliasId=agent_alias_id
                            )
                            logger.info(f"Successfully deleted alias id: {agent_alias_id}")
                        except botocore.exceptions.ClientError as alias_error:
                            # Capture error but continue with other aliases
                            error_msg = f"Error deleting alias {agent_alias_id}: {str(alias_error)}"
                            logger.warning(error_msg)
                            delete_errors.append(error_msg)
                            # Continue deleting other aliases
                except Exception as list_error:
                    error_msg = f"Error listing aliases: {str(list_error)}"
                    logger.warning(error_msg)
                    delete_errors.append(error_msg)
                    # Continue with deletion process
                
                # Try to delete the agent with error handling
                try:
                    response = bedrock_agent.delete_agent(
                        agentId=agent_id, skipResourceInUseCheck=True  # Changed to True for more permissive deletion
                    )
                    logger.info(f"Deleted agent id: {agent_id}.")
                except Exception as agent_error:
                    error_msg = f"Error deleting agent: {str(agent_error)}"
                    logger.warning(error_msg)
                    delete_errors.append(error_msg)
                
                # For Delete operations, always return SUCCESS regardless of errors
                if delete_errors:
                    logger.warning(f"Delete operation completed with {len(delete_errors)} errors: {delete_errors}")
                    response = {"WarningMessage": "Some resources may not have been deleted properly", "Errors": delete_errors}
                else:
                    logger.info("Delete operation completed successfully")
                
                # Always set status to SUCCESS for delete operations
                status = cfnresponse.SUCCESS
                
            except Exception as delete_error:
                # Catch-all for any other errors during delete
                logger.warning(f"Unexpected error during delete operation: {str(delete_error)}")
                response = {"Error": str(delete_error)}
                # Still return SUCCESS for delete operations
                status = cfnresponse.SUCCESS
                
        else:
            logger.info("Continuing without action.")

    except Exception as e:
        # Log the error
        logger.error(f"An error occurred: {e}")

        # For Delete operations, return SUCCESS regardless of errors
        if is_delete_operation:
            status = cfnresponse.SUCCESS
            logger.info("Returning SUCCESS despite errors since this is a DELETE operation")
        else:
            status = cfnresponse.FAILED
            
        status_code = 500
        status_body = "An error occurred during the process."
        response = {"Error": str(e)}

    finally:
        logger.info(f"Sending status: {status} with response: {response}")  # Changed from error to info
        cfnresponse.send(event, context, status, response)

    # If everything went well
    return {"statusCode": status_code, "body": status_body}