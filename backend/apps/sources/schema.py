from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SourceTokenAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.sources.authentication.SourceTokenAuthentication"
    name = "sourceBearerAuth"

    def get_security_definition(self, auto_schema: object) -> dict[str, str]:
        return {"type": "http", "scheme": "bearer", "bearerFormat": "Source token"}
