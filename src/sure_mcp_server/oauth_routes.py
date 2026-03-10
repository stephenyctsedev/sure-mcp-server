"""OAuth 2.0 Authorization Code routes for Claude.ai web connector support."""
import html
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route
from sure_mcp_server.auth_db import AuthDB


def make_oauth_routes(auth_db: AuthDB, base_url: str) -> list:
    """Return list of Starlette Routes for OAuth 2.0 endpoints."""

    async def discovery(request: Request) -> JSONResponse:
        return JSONResponse({
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/authorize",
            "token_endpoint": f"{base_url}/token",
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
        })

    async def protected_resource_metadata(request: Request) -> JSONResponse:
        """RFC 9728 Protected Resource Metadata — tells clients which auth server to use."""
        return JSONResponse({
            "resource": base_url,
            "authorization_servers": [base_url],
            "bearer_methods_supported": ["header"],
        })

    async def authorize(request: Request) -> HTMLResponse | RedirectResponse:
        if request.method == "GET":
            return _authorize_form(request)
        return await _authorize_submit(request, auth_db)

    async def token(request: Request) -> JSONResponse:
        form = await request.form()
        if form.get("grant_type") != "authorization_code":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
        code = form.get("code", "")
        api_key = auth_db.exchange_code(code)
        if not api_key:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        access_token = auth_db.create_token(api_key)
        return JSONResponse({"access_token": access_token, "token_type": "bearer"})

    return [
        Route("/.well-known/oauth-authorization-server", discovery),
        Route("/.well-known/oauth-protected-resource", protected_resource_metadata),
        # Handle resource-specific metadata (e.g. /.well-known/oauth-protected-resource/sse)
        Route("/.well-known/oauth-protected-resource/{path:path}", protected_resource_metadata),
        Route("/authorize", authorize, methods=["GET", "POST"]),
        Route("/token", token, methods=["POST"]),
    ]


def _authorize_form(request: Request) -> HTMLResponse:
    params = request.query_params

    def h(key: str) -> str:
        return html.escape(params.get(key, ""), quote=True)

    form_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Connect Sure Finance</title>
  <style>
    body {{ font-family: sans-serif; max-width: 420px; margin: 60px auto; padding: 0 20px; }}
    input[type=password] {{ width: 100%; padding: 8px; margin: 8px 0 16px; box-sizing: border-box; }}
    button {{ padding: 10px 24px; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; }}
  </style>
</head>
<body>
  <h2>Connect Sure Finance</h2>
  <p>Enter your personal Sure API key to connect your account.</p>
  <form method="post" action="/authorize">
    <input type="hidden" name="redirect_uri" value="{h('redirect_uri')}">
    <input type="hidden" name="state" value="{h('state')}">
    <input type="hidden" name="code_challenge" value="{h('code_challenge')}">
    <input type="hidden" name="code_challenge_method" value="{h('code_challenge_method')}">
    <input type="hidden" name="client_id" value="{h('client_id')}">
    <label for="api_key">Sure API Key:</label>
    <input type="password" id="api_key" name="api_key" autofocus placeholder="Paste your API key here">
    <button type="submit">Connect</button>
  </form>
  <p><small>Get your API key from Sure: Settings &gt; API Key</small></p>
</body>
</html>"""
    return HTMLResponse(form_html)


async def _authorize_submit(request: Request, auth_db: AuthDB) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    api_key = str(form.get("api_key", "")).strip()
    redirect_uri = str(form.get("redirect_uri", ""))
    state = str(form.get("state", ""))

    if not api_key:
        return HTMLResponse("API key is required.", status_code=400)
    if not redirect_uri:
        return HTMLResponse("redirect_uri is required.", status_code=400)

    code = auth_db.create_auth_code(api_key, state)
    return RedirectResponse(f"{redirect_uri}?code={code}&state={state}", status_code=302)
