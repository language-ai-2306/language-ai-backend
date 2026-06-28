import uuid
import boto3
from botocore.exceptions import ClientError

from app.config.settings import settings

_s3 = None


def _client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")  # credentials from env: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
    return _s3


def upload_audio(file_bytes: bytes, session_id: str, turn_number: int, speaker: str) -> str:
    """Upload audio bytes to S3 and return the object URL.

    Args:
        file_bytes:   Raw audio bytes to upload.
        session_id:   UUID string grouping this conversation session.
        turn_number:  Which turn this audio belongs to.
        speaker:      "child" or "ai" — used in the S3 key path.

    Returns:
        HTTPS URL of the uploaded object.
    """
    key = f"conversations/{session_id}/turn_{turn_number}/{speaker}.wav"
    _client().put_object(
        Bucket=settings.s3_bucket_name,
        Key=key,
        Body=file_bytes,
        ContentType="audio/wav",
    )
    return f"https://{settings.s3_bucket_name}.s3.amazonaws.com/{key}"


def delete_audio(url: str) -> None:
    """Delete an object given its S3 URL. Silently ignores missing objects."""
    if not url:
        return
    # Extract key from https://<bucket>.s3.amazonaws.com/<key>
    key = url.split(".amazonaws.com/", 1)[-1]
    try:
        _client().delete_object(Bucket=settings.s3_bucket_name, Key=key)
    except ClientError:
        pass
