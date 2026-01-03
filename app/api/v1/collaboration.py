from uuid import UUID
from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from app.core.dependencies import get_current_user, get_session
from app.db.schema import User
from app.models.product_version import VersionDataUpdate
from app.models.data_contribution_request import ReviewPayload
from app.services.collaboration import CollaborationService

router = APIRouter()


def get_collab_service(session: Session = Depends(get_session)) -> CollaborationService:
    return CollaborationService(session)


@router.get(
    "/requests/{request_id}",
    status_code=status.HTTP_200_OK,
    summary="Get Request Data",
    description="Fetch the current Product Version data associated with a specific request. Used by Suppliers to load the form."
)
def get_request_data(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    service: CollaborationService = Depends(get_collab_service)
):
    # Note: You might want to create a specific Response Model for this in app/models/request.py
    # combining the Request Info + The Product Version Data
    return service.get_request(current_user, request_id)


@router.put(
    "/requests/{request_id}/data",
    status_code=status.HTTP_200_OK,
    summary="Save Draft Data",
    description="Supplier saves work-in-progress (Materials, Certs, Supply Chain). Updates the Current Version."
)
def update_draft_data(
    request_id: UUID,
    data: VersionDataUpdate,
    current_user: User = Depends(get_current_user),
    service: CollaborationService = Depends(get_collab_service)
):
    return service.update_data(current_user, request_id, data)


@router.post(
    "/requests/{request_id}/submit",
    status_code=status.HTTP_200_OK,
    summary="Submit to Brand",
    description="Locks the data and changes status to SUBMITTED. Passes control back to the Brand."
)
def submit_request(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    service: CollaborationService = Depends(get_collab_service)
):
    return service.submit_request(current_user, request_id)


@router.post(
    "/requests/{request_id}/review",
    status_code=status.HTTP_200_OK,
    summary="Review Submission",
    description="Brand Approves (Finalizes) or Rejects (Clones Version & Requests Changes) the submission."
)
def review_request(
    request_id: UUID,
    payload: ReviewPayload,
    current_user: User = Depends(get_current_user),
    service: CollaborationService = Depends(get_collab_service)
):
    return service.review_request(current_user, request_id, payload)
