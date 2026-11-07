import threading
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from .config import Settings, ROOT
from .db import make_db
from .models import ImportRun
from .security.links import key
from .api.routes import router
from starlette.middleware.cors import CORSMiddleware


def create_app(settings=None, initialize=False):
    settings = settings or Settings()
    engine, factory = make_db(settings, initialize)

    @asynccontextmanager
    async def lifespan(app):
        from .importers.lock import import_active
        if not import_active(settings):
            with factory() as db:
                for run in db.scalars(select(ImportRun).where(ImportRun.status.in_(['pending', 'running']))):
                    run.status = 'interrupted'
                db.commit()
        yield
        engine.dispose()

    app = FastAPI(title='ДРЕВО', version='1.0.0', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings, app.state.engine, app.state.factory = settings, engine, factory
    app.state.secret = key(settings)
    app.state.image_semaphore = threading.BoundedSemaphore(2)
    app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=False, allow_methods=['GET', 'HEAD', 'POST', 'PATCH'], allow_headers=['Authorization', 'Content-Type'])

    @app.middleware('http')
    async def security_headers(request: Request, call_next):
        # Read through the ASGI stream too: Content-Length is not a trusted size boundary.
        if request.method in ('POST', 'PATCH', 'PUT'):
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > settings.max_message_bytes:
                    return JSONResponse({'detail': 'Превышен лимит размера запроса'}, status_code=413)
                chunks.append(chunk)
            body = b''.join(chunks)
            request._body = body
        response = await call_next(request)
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        if request.url.path.startswith(('/ai/images/', '/ai/crops/')):
            response.headers['CDN-Cache-Control'] = 'no-store'
            response.headers['Vercel-CDN-Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(ValidationError)
    async def validation_error(request, exc):
        return JSONResponse({'detail': str(exc)[:2000]}, status_code=422)

    app.include_router(router)
    dist = ROOT / 'frontend' / 'dist'
    if dist.is_dir():
        app.mount('/', StaticFiles(directory=dist, html=True), name='frontend')
    return app


app = create_app()
