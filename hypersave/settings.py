from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_name: str
    bot_token: str
    api_id: int
    api_hash: str
    database_url: str
    private_group_id: int
    admin_ids: list[int] | int

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "allow"

    @field_validator("admin_ids", mode="before")
    def parse_admin_ids(cls, value):
        if isinstance(value, str):
            if "," in value:
                return [int(id.strip()) for id in value.split(",")]
            else:
                return [int(value)]
        elif isinstance(value, int):
            return [value]
        return value

    # @field_validator("private_group_id", mode="before")
    # def parse_target_channel(cls, value):
    #     if isinstance(value, str):
    #         if "," in value:
    #             return [int(id.strip()) for id in value.split(",")]
    #         else:
    #             return [int(value)]
    #     elif isinstance(value, int):
    #         return [value]
    #     return value
