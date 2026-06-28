import uuid
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config.settings import settings

_s3 = None


def _client():
    global _s3
    if _s3 is None:
        # Pass credentials explicitly from settings: they live in .env, which
        # boto3 itself does not read. Falls back to boto3's default credential
        # chain (env vars / ~/.aws / IAM role) when the settings are blank.
        # signature_version=s3v4 → presigned URLs use the modern regional
        # endpoint and signing scheme (works in every region).
        kwargs = {
            "region_name": settings.aws_region,
            "config": Config(signature_version="s3v4"),
        }
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        _s3 = boto3.client("s3", **kwargs)
    return _s3


# Each speaker's audio goes into its own top-level S3 folder.
_FOLDER_BY_SPEAKER = {"child": "children_voice", "ai": "AI_voice"}


def upload_audio(
    file_bytes: bytes,
    session_id: str,
    turn_number: int,
    speaker: str,
    ext: str = "wav",
    content_type: str = "audio/wav",
) -> str:
    """Upload audio bytes to S3 and return the object URL.

    The file is stored directly inside one of two folders — `children_voice/`
    (the child's recording) or `AI_voice/` (Ollie's reply) — named by session
    and turn so each object is unique and traceable back to its conversation.

    Args:
        file_bytes:   Raw audio bytes to upload.
        session_id:   UUID string grouping this conversation session.
        turn_number:  Which turn this audio belongs to.
        speaker:      "child" or "ai" — selects the destination folder.
        ext:          File extension without dot (default "wav").
        content_type: MIME type for the S3 object (default "audio/wav").

    Returns:
        The object's full canonical S3 URL (e.g.
        "https://<bucket>.s3.<region>.amazonaws.com/children_voice/<sid>_turn_2.wav").
        The bucket is PRIVATE, so this URL is not directly accessible — serve the
        file via `presigned_url(url)`, which signs it for temporary access.
    """
    folder = _FOLDER_BY_SPEAKER.get(speaker, speaker)
    key = f"{folder}/{session_id}_turn_{turn_number}.{ext}"
    _client().put_object(
        Bucket=settings.s3_bucket_name,
        Key=key,
        Body=file_bytes,
        ContentType=content_type,
    )
    return f"https://{settings.s3_bucket_name}.s3.{settings.aws_region}.amazonaws.com/{key}"


def presigned_url(key_or_url: str, expires_in: int = 3600) -> str:
    """Return a temporary, signed GET URL for a private S3 object.

    The bucket is private (children's recordings must never be public), so we
    serve objects via short-lived presigned URLs generated on demand — and a
    fresh one each time, so links never go stale. boto3 signs for the client's
    configured region, so the URL uses the correct regional endpoint.

    Accepts an object key ("children_voice/..wav") or a full S3 URL (the key is
    extracted, for backward compatibility with rows that stored a URL).
    """
    key = key_or_url
    if key_or_url.startswith("http"):
        key = key_or_url.split(".amazonaws.com/", 1)[-1].split("?", 1)[0]
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket_name, "Key": key},
        ExpiresIn=expires_in,
    )


def upload_practice_audio(
    file_bytes: bytes,
    user_id: int,
    ext: str = "wav",
    content_type: str = "audio/wav",
) -> str:
    """Upload a Repeat-After-Me recording to S3 and return the object URL.

    Keyed by user so a therapist's dashboard can browse a patient's recordings.
    A random UUID keeps each attempt's object distinct.
    """
    key = f"practice/{user_id}/{uuid.uuid4()}.{ext}"
    _client().put_object(
        Bucket=settings.s3_bucket_name,
        Key=key,
        Body=file_bytes,
        ContentType=content_type,
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
