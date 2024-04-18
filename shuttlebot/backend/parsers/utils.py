from loguru import logger as logging


def validate_api_response(response, content_type: str, url: str):
    """Validating API response based on the status codes and content type"""
    match response.status_code, content_type:
        case (200, "application/json"):
            json_response = response.json()
            logging.debug(f"Raw response for url: {url} \n{json_response}")
            return json_response
        case (_, c) if c != "application/json":
            logging.error(
                f"Response content-type is not application/json"
                f"\nResponse: {response}"
            )
            return {}
        case (_, _):
            logging.error(
                f"Request failed: status code {response.status_code}"
                f"\nResponse: {response}"
            )
            return {}
