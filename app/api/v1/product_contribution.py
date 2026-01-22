import uuid
import json
from typing import List
from fastapi import APIRouter, Depends, status, BackgroundTasks, Body, Form, File, UploadFile, HTTPException

from app.db.schema import User
from app.core.dependencies import get_current_user, get_product_contribution_service
from app.services.product_contribution import ProductContributionService
from app.models.product_contribution import (
    RequestReadList,
    RequestReadDetail,
    RequestAction,
    TechnicalDataUpdate,
    ProductAssignmentRequest,
    ProductVersionDetailRead,
    ProductCollaborationStatusRead,
    CancelRequestPayload,
    ReviewPayload
)

router = APIRouter()

# ==============================================================================
# SUPPLIER WORKFLOW (INCOMING REQUESTS)
# ==============================================================================


@router.get(
    "/",
    response_model=List[RequestReadList],
    status_code=status.HTTP_200_OK,
    summary="List Incoming Requests",
    description="Supplier Dashboard: List all contribution requests assigned to this supplier tenant."
)
def list_incoming_requests(
    current_user: User = Depends(get_current_user),
    service: ProductContributionService = Depends(
        get_product_contribution_service)
):
    return service.list_requests(current_user)


@router.get(
    "/{request_id}",
    response_model=RequestReadDetail,
    status_code=status.HTTP_200_OK,
    summary="Get Request Detail",
    description="Returns the full context for the Supplier Contribution Page, including Product Identity, History, and Draft Data."
)
def get_request_detail(
    request_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: ProductContributionService = Depends(
        get_product_contribution_service)
):
    return service.get_request_detail(current_user, request_id)


@router.post(
    "/{request_id}/action",
    status_code=status.HTTP_200_OK,
    summary="Handle Workflow Action",
    description="Change request state (e.g., Accept, Decline). If 'Submit' is chosen, the data is locked and sent to the Brand for review."
)
def handle_workflow_action(
    request_id: uuid.UUID,
    data: RequestAction,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: ProductContributionService = Depends(
        get_product_contribution_service)
):
    return service.handle_workflow_action(current_user, request_id, data, background_tasks)


@router.put(
    "/{request_id}/data",
    status_code=status.HTTP_200_OK,
    summary="Save Technical Data",
    description="Save the form data (BOM, Supply Chain, Impacts) via Multipart/Form-Data. Handles JSON payload + File Uploads."
)
def save_technical_data(
    request_id: uuid.UUID,
    payload: str = Form(
        ..., description="JSON string matching the TechnicalDataUpdate model."),
    files: List[UploadFile] = File(
        default=[], description="List of certificate or evidence files."),
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user),
    service: ProductContributionService = Depends(
        get_product_contribution_service)
):
    try:
        # Parse the JSON string back to Dict
        payload_dict = json.loads(payload)
        # Validate with Pydantic
        data = TechnicalDataUpdate(**payload_dict)
    except Exception as e:
        raise HTTPException(
            status_code=422, detail=f"Invalid JSON payload: {str(e)}")

    return service.save_draft_data(current_user, request_id, data, files, background_tasks)


@router.post(
    "/{request_id}/comments",
    status_code=status.HTTP_201_CREATED,
    summary="Add Comment",
    description="Add a message to the collaboration history log."
)
def add_comment(
    request_id: uuid.UUID,
    body: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    service: ProductContributionService = Depends(
        get_product_contribution_service)
):
    return service.add_comment(current_user, request_id, body)


# ==============================================================================
# BRAND WORKFLOW (ASSIGNMENT & REVIEW)
# ==============================================================================


@router.post(
    "/{product_id}/assign",
    status_code=status.HTTP_201_CREATED,
    summary="Assign Supplier",
    description="Assigns a Product to a Supplier. Converts pending drafts into real Versions and sends a Data Request."
)
def assign_product_to_supplier(
    product_id: uuid.UUID,
    data: ProductAssignmentRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: ProductContributionService = Depends(
        get_product_contribution_service)
):
    return service.assign_product(current_user, product_id, data, background_tasks)


@router.get(
    "/{product_id}/technical-data",
    response_model=ProductVersionDetailRead,
    status_code=status.HTTP_200_OK,
    summary="Get Technical Data",
    description="Get the full technical breakdown (Materials, Supply Chain, Impact) of the Latest Active Version."
)
def get_product_technical_data(
    product_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: ProductContributionService = Depends(
        get_product_contribution_service)
):
    return service.get_latest_version_detail(current_user, product_id)


@router.get(
    "/{product_id}/collaboration-status",
    response_model=ProductCollaborationStatusRead,
    status_code=status.HTTP_200_OK,
    summary="Get Collaboration Status",
    description="Get the workflow status. Reveals if the supplier has accepted, submitted, or if the version is locked."
)
def get_product_collaboration_status(
    product_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: ProductContributionService = Depends(
        get_product_contribution_service)
):
    return service.get_collaboration_status(current_user, product_id)


@router.post(
    "/{product_id}/requests/{request_id}/cancel",
    status_code=status.HTTP_200_OK,
    summary="Cancel Request",
    description="Brand cancels a pending request to a supplier."
)
def cancel_product_request(
    product_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: CancelRequestPayload,
    current_user: User = Depends(get_current_user),
    service: ProductContributionService = Depends(
        get_product_contribution_service)
):
    return service.cancel_request(current_user, product_id, request_id, payload.reason)


@router.post(
    "/{product_id}/requests/{request_id}/review",
    status_code=status.HTTP_200_OK,
    summary="Review Submission",
    description="Brand approves or requests changes on a supplier submission."
)
def review_product_request(
    product_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: ReviewPayload,
    current_user: User = Depends(get_current_user),
    service: ProductContributionService = Depends(
        get_product_contribution_service)
):
    return service.review_submission(current_user, product_id, request_id, payload.action, payload.comment)
