from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, status, BackgroundTasks, Body, Form, File, UploadFile, HTTPException

import json
from app.db.schema import User
from app.core.dependencies import get_current_user, get_product_contribution_service
from app.services.product_contribution import ProductContributionService
from app.models.product_contribution import (
    RequestReadList,
    RequestReadDetail,
    RequestAction,
    TechnicalDataUpdate
)

router = APIRouter()


@router.get("/", response_model=List[RequestReadList])
def list_incoming_requests(
    current_user: User = Depends(get_current_user),
    service: ProductContributionService = Depends(
        get_product_contribution_service)
):
    """
    Supplier Dashboard: List all requests assigned to this supplier.
    """
    return service.list_requests(current_user)


@router.get("/{request_id}", response_model=RequestReadDetail)
def get_request_detail(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductContributionService = Depends(
        get_product_contribution_service)
):
    """
    Returns the FULL context for the Supplier Contribution Page.
    Includes Product Images, History, and Draft Data.
    """
    return service.get_request_detail(current_user, request_id)


@router.post("/{request_id}/action", status_code=status.HTTP_200_OK)
def handle_workflow_action(
    request_id: UUID,
    data: RequestAction,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: ProductContributionService = Depends(
        get_product_contribution_service)
):
    """
    Change State: Accept, Decline, or Submit.
    If 'submit', the data is locked and sent to Brand.
    """
    return service.handle_workflow_action(current_user, request_id, data, background_tasks)


@router.put("/{request_id}/data", status_code=status.HTTP_200_OK)
def save_technical_data(
    request_id: UUID,
    payload: str = Form(...),
    files: List[UploadFile] = File(default=[]),
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user),
    service: ProductContributionService = Depends(
        get_product_contribution_service)
):
    """
    Saves the form data via Multipart/Form-Data.
    Parses 'payload' string into Pydantic model.
    Matches 'files' to certificates via temp_ids.
    """
    try:
        # Parse the JSON string back to Dict
        payload_dict = json.loads(payload)
        # Validate with Pydantic
        data = TechnicalDataUpdate(**payload_dict)
    except Exception as e:
        raise HTTPException(
            status_code=422, detail=f"Invalid JSON payload: {str(e)}")

    return service.save_draft_data(current_user, request_id, data, files, background_tasks)


@router.post("/{request_id}/comments", status_code=status.HTTP_201_CREATED)
def add_comment(
    request_id: UUID,
    body: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    service: ProductContributionService = Depends(
        get_product_contribution_service)
):
    """
    Add a message to the collaboration history.
    """
    return service.add_comment(current_user, request_id, body)
