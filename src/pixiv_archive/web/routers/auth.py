from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Author, Illust, IllustTag, Tag
from pixiv_archive.web.auth import (
    SessionSigner,
    clear_session_cookie,
    get_signer,
    require_auth,
    set_session_cookie,
)
from pixiv_archive.web.deps import get_session, get_settings
from pixiv_archive.web.schemas import AuthorOut, LoginRequest, MeResponse, TagOut

router = APIRouter(prefix="/api/auth", tags=["auth"])
gallery_router = APIRouter(tags=["gallery"])


@router.post("/login", response_model=MeResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    signer: SessionSigner = Depends(get_signer),  # noqa: B008
) -> MeResponse:
    settings = get_settings(request)
    expected = settings.auth_token
    if not expected:
        raise HTTPException(status_code=503, detail="AUTH_TOKEN is not configured")
    if payload.token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    set_session_cookie(response, signer)
    return MeResponse(authenticated=True)


@router.post("/logout", response_model=MeResponse)
async def logout(response: Response, _: str = Depends(require_auth)) -> MeResponse:  # noqa: B008
    clear_session_cookie(response)
    return MeResponse(authenticated=False)


@router.get("/me", response_model=MeResponse)
async def me(
    request: Request,
    signer: SessionSigner = Depends(get_signer),  # noqa: B008
) -> MeResponse:
    token = request.cookies.get("session")
    return MeResponse(authenticated=signer.verify(token))


protected = APIRouter(
    prefix="/api",
    tags=["gallery"],
    dependencies=[Depends(require_auth)],  # noqa: B008
)


@protected.get("/authors", response_model=list[AuthorOut])
async def authors(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    limit: int = 100,
    offset: int = 0,
) -> list[AuthorOut]:
    rows = (
        await session.execute(
            select(Author, func.count(Illust.pid))
            .join(Illust, Illust.author_id == Author.id)
            .where(Illust.state == "active")
            .group_by(Author.id)
            .order_by(func.count(Illust.pid).desc(), Author.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [
        AuthorOut(id=author.id, name=author.name, account=author.account, illust_count=count)
        for author, count in rows
    ]


@protected.get("/tags", response_model=list[TagOut])
async def tags(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    limit: int = 200,
    offset: int = 0,
) -> list[TagOut]:
    rows = (
        await session.execute(
            select(Tag, func.count(IllustTag.pid))
            .join(IllustTag, IllustTag.tag_id == Tag.id)
            .group_by(Tag.id)
            .order_by(func.count(IllustTag.pid).desc(), Tag.name)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [
        TagOut(name=tag.name, translated_name=tag.translated_name, illust_count=count)
        for tag, count in rows
    ]
