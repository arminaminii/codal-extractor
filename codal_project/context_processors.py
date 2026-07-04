def nav_context(request):
    """Add nav_page to all templates based on current URL."""
    path = request.path
    if path == "/":
        return {"nav_page": "home"}
    elif path.startswith("/reports/"):
        symbol = path.strip("/").split("/")[-1] if "/" in path else ""
        return {
            "nav_page": "reports",
            "reports_url": f"/reports/{symbol}/" if symbol else "/",
        }
    return {"nav_page": "home"}