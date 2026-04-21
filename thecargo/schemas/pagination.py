from fastapi_pagination import Page
from fastapi_pagination.customization import CustomizedPage, UseParamsFields

CustomPage = CustomizedPage[
    Page,
    UseParamsFields(size=50),
]
