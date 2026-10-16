"""Alibaba SDK boundary. Import SDKs only when this optional provider is constructed."""

import json
from typing import Protocol

from app.phone.config import PhoneSettings


class PhoneProvider(Protocol):
    def verify_captcha(self, token: str) -> bool: ...
    def send(self, phone: str, challenge_id: str) -> None: ...
    def verify(self, phone: str, challenge_id: str, code: str) -> bool: ...


class AliyunPhoneProvider:
    def __init__(self, settings: PhoneSettings):
        from alibabacloud_captcha20230305 import models as captcha_models
        from alibabacloud_captcha20230305.client import Client as CaptchaClient
        from alibabacloud_dypnsapi20170525 import models as sms_models
        from alibabacloud_dypnsapi20170525.client import Client as SmsClient
        from alibabacloud_tea_openapi.models import Config
        from alibabacloud_tea_util.models import RuntimeOptions

        self.settings = settings
        self.captcha_models = captcha_models
        self.sms_models = sms_models
        self.options = RuntimeOptions(connect_timeout=2000, read_timeout=5000, autoretry=False)
        config = dict(
            access_key_id=settings.access_key_id.get_secret_value(),
            access_key_secret=settings.access_key_secret.get_secret_value(),
            protocol="https",
            connect_timeout=2000,
            read_timeout=5000,
        )
        self.captcha = CaptchaClient(Config(endpoint="captcha.cn-shanghai.aliyuncs.com", **config))
        self.sms = SmsClient(Config(endpoint="dypnsapi.aliyuncs.com", **config))

    def verify_captcha(self, token: str) -> bool:
        response = self.captcha.verify_intelligent_captcha_with_options(
            self.captcha_models.VerifyIntelligentCaptchaRequest(
                captcha_verify_param=token,
                scene_id=self.settings.captcha_scene_id,
            ),
            self.options,
        ).body
        return bool(
            response
            and response.success
            and response.result
            and response.result.verify_result is True
        )

    def send(self, phone: str, challenge_id: str) -> None:
        response = self.sms.send_sms_verify_code_with_options(
            self.sms_models.SendSmsVerifyCodeRequest(
                phone_number=phone.removeprefix("+86"),
                country_code="86",
                out_id=challenge_id,
                scheme_name=self.settings.sms_scheme_name,
                sign_name=self.settings.sms_sign_name,
                template_code=self.settings.sms_template_code,
                template_param=json.dumps({"code": "##code##", "min": "5"}),
                code_length=6,
                code_type=1,
                valid_time=300,
                interval=60,
                duplicate_policy=1,
                return_verify_code=False,
                auto_retry=0,
            ),
            self.options,
        ).body
        if not response or not response.success or response.code != "OK":
            raise RuntimeError("SMS provider rejected request")

    def verify(self, phone: str, challenge_id: str, code: str) -> bool:
        response = self.sms.check_sms_verify_code_with_options(
            self.sms_models.CheckSmsVerifyCodeRequest(
                phone_number=phone.removeprefix("+86"),
                country_code="86",
                out_id=challenge_id,
                scheme_name=self.settings.sms_scheme_name,
                verify_code=code,
            ),
            self.options,
        ).body
        return bool(
            response
            and response.success
            and response.code == "OK"
            and response.model
            and response.model.verify_result == "PASS"
        )
