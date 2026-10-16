from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class PhoneSettings(BaseSettings):
    # Loaded independently and guarded by the phone runtime, never core Settings.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    enabled: bool = Field(False, alias="MVP_PHONE_VERIFICATION_ENABLED")
    encryption_keys: SecretStr = Field(SecretStr("{}"), alias="MVP_PHONE_ENCRYPTION_KEYS")
    active_key_id: str = Field("v1", alias="MVP_PHONE_ENCRYPTION_ACTIVE_KEY_ID")
    lookup_key: SecretStr = Field(SecretStr(""), alias="MVP_PHONE_LOOKUP_KEY")
    access_key_id: SecretStr = Field(SecretStr(""), alias="MVP_ALIYUN_ACCESS_KEY_ID")
    access_key_secret: SecretStr = Field(SecretStr(""), alias="MVP_ALIYUN_ACCESS_KEY_SECRET")
    captcha_prefix: str = Field("", alias="MVP_ALIYUN_CAPTCHA_PREFIX")
    captcha_scene_id: str = Field("", alias="MVP_ALIYUN_CAPTCHA_SCENE_ID")
    sms_sign_name: str = Field("", alias="MVP_ALIYUN_SMS_SIGN_NAME")
    sms_template_code: str = Field("", alias="MVP_ALIYUN_SMS_TEMPLATE_CODE")
    sms_scheme_name: str = Field("", alias="MVP_ALIYUN_SMS_SCHEME_NAME")
    user_hour_limit: int = Field(5, ge=1, alias="MVP_PHONE_USER_HOUR_LIMIT")
    user_day_limit: int = Field(10, ge=1, alias="MVP_PHONE_USER_DAY_LIMIT")
    number_hour_limit: int = Field(5, ge=1, alias="MVP_PHONE_NUMBER_HOUR_LIMIT")
    number_day_limit: int = Field(10, ge=1, alias="MVP_PHONE_NUMBER_DAY_LIMIT")
    global_hour_limit: int = Field(100, ge=1, alias="MVP_PHONE_GLOBAL_HOUR_LIMIT")
    global_day_limit: int = Field(500, ge=1, alias="MVP_PHONE_GLOBAL_DAY_LIMIT")

    def provider_ready(self) -> bool:
        return (
            all(
                (
                    self.access_key_id.get_secret_value(),
                    self.access_key_secret.get_secret_value(),
                    self.captcha_prefix,
                    self.captcha_scene_id,
                    self.sms_sign_name,
                    self.sms_template_code,
                    self.sms_scheme_name,
                )
            )
            and len(self.sms_scheme_name) <= 20
        )
