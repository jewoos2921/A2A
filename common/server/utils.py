from common.types import (JSONRPCResponse,
                          ContentTypeNotSupportedError,
                          UnsupportedOperationalError)
from typing import List


def are_modalities_compatible(
        server_output_modes: List[str],
        client_output_modes: List[str]
):
    if client_output_modes is None or len(client_output_modes) == 0:
        return True
    if server_output_modes is None or len(server_output_modes) == 0:
        return True
    return any(x in server_output_modes for x in client_output_modes)


def new_incompatible_types_error(request_id):
    return JSONRPCResponse(
        id=request_id,
        error=ContentTypeNotSupportedError(
            message="Content type not supported"
        )
    )


def new_not_implemented_error(request_id):
    return JSONRPCResponse(
        id=request_id,
        error=UnsupportedOperationalError(
            message="Operation not supported"
        )
    )
