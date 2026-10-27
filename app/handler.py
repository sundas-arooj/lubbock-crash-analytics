"""Lambda entrypoint. Local runs use uvicorn and do not import this module."""

from mangum import Mangum

from app.api import app

handler = Mangum(app, lifespan="off")
