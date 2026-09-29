import logging
import threading
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)


def send_verification_email_async(to_email: str, recipient_name: str, verification_code: str):
    """
    Sends verification email asynchronously in a background thread so the HTTP response stays instant.
    """
    thread = threading.Thread(
        target=_send_verification_email_sync,
        args=(to_email, recipient_name, verification_code),
        daemon=True
    )
    thread.start()


def _send_verification_email_sync(to_email: str, recipient_name: str, verification_code: str):
    try:
        subject = f"[{verification_code}] Mã xác thực tài khoản SupplyForge AI"
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'SupplyForge AI <noreply@supplyforge.ai>')

        # Plain text fallback
        text_content = (
            f"Xin chào {recipient_name},\n\n"
            f"Mã xác thực tài khoản SupplyForge AI của bạn là: {verification_code}\n\n"
            f"Mã này có hiệu lực trong 24 giờ. Vui lòng không chia sẻ mã này với bất kỳ ai.\n\n"
            f"Trân trọng,\nĐội ngũ SupplyForge AI"
        )

        # Professional HTML SaaS Template
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>Mã xác thực SupplyForge AI</title>
        </head>
        <body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #f8fafc; padding: 40px 20px;">
            <tr>
              <td align="center">
                <table role="presentation" width="100%" style="max-width: 520px; background-color: #ffffff; border-radius: 24px; border: 1px solid #e2e8f0; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05); overflow: hidden;">
                  
                  <!-- Header Logo -->
                  <tr>
                    <td style="padding: 32px 32px 20px 32px; text-align: center; border-bottom: 1px solid #f1f5f9;">
                      <div style="display: inline-flex; align-items: center; justify-content: center;">
                        <span style="font-size: 24px; font-weight: 900; color: #0f172a; letter-spacing: -0.5px;">SupplyForge <span style="color: #4f46e5;">AI</span></span>
                      </div>
                      <p style="margin: 6px 0 0 0; font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 1.2px;">Quản lý Rủi ro Tồn kho &amp; Dòng vốn</p>
                    </td>
                  </tr>

                  <!-- Main Body -->
                  <tr>
                    <td style="padding: 32px;">
                      <h1 style="margin: 0 0 12px 0; font-size: 20px; font-weight: 800; color: #0f172a; text-align: center;">Xác thực địa chỉ Email</h1>
                      <p style="margin: 0 0 24px 0; font-size: 14px; line-height: 1.6; color: #475569; text-align: center;">
                        Xin chào <strong>{recipient_name}</strong>,<br>
                        Cảm ơn bạn đã tạo tài khoản tại SupplyForge AI. Vui lòng sử dụng mã 6 chữ số dưới đây để kích hoạt tài khoản:
                      </p>

                      <!-- OTP Highlight Box -->
                      <div style="background: linear-gradient(135deg, #4f46e5 0%, #3b82f6 100%); border-radius: 16px; padding: 24px; text-align: center; margin-bottom: 24px; box-shadow: 0 4px 12px rgba(79, 70, 229, 0.25);">
                        <span style="display: block; font-size: 11px; font-weight: 700; color: #e0e7ff; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 8px;">MÃ XÁC THỰC CỦA BẠN</span>
                        <span style="font-family: 'Consolas', 'Courier New', Courier, monospace; font-size: 38px; font-weight: 900; color: #ffffff; letter-spacing: 8px; display: inline-block;">{verification_code}</span>
                      </div>

                      <p style="margin: 0 0 20px 0; font-size: 12px; color: #64748b; text-align: center; line-height: 1.6;">
                        Mã này có hiệu lực trong vòng <strong>24 giờ</strong>.<br>
                        Vì an toàn tài khoản, tuyệt đối không chia sẻ mã này với bất kỳ ai.
                      </p>
                    </td>
                  </tr>

                  <!-- Footer -->
                  <tr>
                    <td style="padding: 24px 32px; background-color: #f8fafc; border-top: 1px solid #f1f5f9; text-align: center;">
                      <p style="margin: 0 0 8px 0; font-size: 11px; color: #94a3b8; line-height: 1.4;">
                        Nếu bạn không thực hiện yêu cầu đăng ký này, vui lòng bỏ qua email này.
                      </p>
                      <p style="margin: 0; font-size: 11px; font-weight: 600; color: #64748b;">
                        © 2026 SupplyForge AI Inc. All rights reserved.
                      </p>
                    </td>
                  </tr>

                </table>
              </td>
            </tr>
          </table>
        </body>
        </html>
        """

        msg = EmailMultiAlternatives(subject, text_content, from_email, [to_email])
        msg.attach_alternative(html_content, "text/html")
        msg.send(fail_silently=False)
        logger.info(f"[Email Success] Verification code sent to {to_email}")
    except Exception as e:
        logger.error(f"[Email Error] Failed to send email to {to_email}: {e}")


def send_password_reset_email_async(to_email: str, recipient_name: str, reset_code: str):
    """
    Sends password reset code asynchronously in a background thread.
    """
    thread = threading.Thread(
        target=_send_password_reset_email_sync,
        args=(to_email, recipient_name, reset_code),
        daemon=True
    )
    thread.start()


def _send_password_reset_email_sync(to_email: str, recipient_name: str, reset_code: str):
    try:
        subject = f"[{reset_code}] Mã khôi phục mật khẩu SupplyForge AI"
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'SupplyForge AI <ndaitung28092005@gmail.com>')

        text_content = (
            f"Xin chào {recipient_name},\n\n"
            f"Mã khôi phục mật khẩu SupplyForge AI của bạn là: {reset_code}\n\n"
            f"Mã này có hiệu lực trong 1 giờ. Nếu bạn không yêu cầu đặt lại mật khẩu, vui lòng bỏ qua email này.\n\n"
            f"Trân trọng,\nĐội ngũ SupplyForge AI"
        )

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>Khôi phục mật khẩu SupplyForge AI</title>
        </head>
        <body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #f8fafc; padding: 40px 20px;">
            <tr>
              <td align="center">
                <table role="presentation" width="100%" style="max-width: 520px; background-color: #ffffff; border-radius: 24px; border: 1px solid #e2e8f0; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05); overflow: hidden;">
                  
                  <!-- Header Logo -->
                  <tr>
                    <td style="padding: 32px 32px 20px 32px; text-align: center; border-bottom: 1px solid #f1f5f9;">
                      <div style="display: inline-flex; align-items: center; justify-content: center;">
                        <span style="font-size: 24px; font-weight: 900; color: #0f172a; letter-spacing: -0.5px;">SupplyForge <span style="color: #e11d48;">AI</span></span>
                      </div>
                      <p style="margin: 6px 0 0 0; font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 1.2px;">Khôi phục mật khẩu tài khoản</p>
                    </td>
                  </tr>

                  <!-- Main Body -->
                  <tr>
                    <td style="padding: 32px;">
                      <h1 style="margin: 0 0 12px 0; font-size: 20px; font-weight: 800; color: #0f172a; text-align: center;">Yêu cầu đặt lại mật khẩu</h1>
                      <p style="margin: 0 0 24px 0; font-size: 14px; line-height: 1.6; color: #475569; text-align: center;">
                        Xin chào <strong>{recipient_name}</strong>,<br>
                        Chúng tôi nhận được yêu cầu khôi phục mật khẩu cho tài khoản của bạn. Sử dụng mã 6 chữ số dưới đây:
                      </p>

                      <!-- Reset Code Box -->
                      <div style="background: linear-gradient(135deg, #e11d48 0%, #f43f5e 100%); border-radius: 16px; padding: 24px; text-align: center; margin-bottom: 24px; box-shadow: 0 4px 12px rgba(225, 29, 72, 0.25);">
                        <span style="display: block; font-size: 11px; font-weight: 700; color: #ffe4e6; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 8px;">MÃ KHÔI PHỤC MẬT KHẨU</span>
                        <span style="font-family: 'Consolas', 'Courier New', Courier, monospace; font-size: 38px; font-weight: 900; color: #ffffff; letter-spacing: 8px; display: inline-block;">{reset_code}</span>
                      </div>

                      <p style="margin: 0 0 20px 0; font-size: 12px; color: #64748b; text-align: center; line-height: 1.6;">
                        ⏱️ Mã này có hiệu lực trong vòng <strong>1 giờ</strong>.<br>
                        🔒 Nếu bạn không thực hiện yêu cầu này, vui lòng bỏ qua email và mật khẩu của bạn sẽ giữ nguyên.
                      </p>
                    </td>
                  </tr>

                  <!-- Footer -->
                  <tr>
                    <td style="padding: 24px 32px; background-color: #f8fafc; border-top: 1px solid #f1f5f9; text-align: center;">
                      <p style="margin: 0; font-size: 11px; font-weight: 600; color: #64748b;">
                        © 2026 SupplyForge AI Inc. All rights reserved.
                      </p>
                    </td>
                  </tr>

                </table>
              </td>
            </tr>
          </table>
        </body>
        </html>
        """

        msg = EmailMultiAlternatives(subject, text_content, from_email, [to_email])
        msg.attach_alternative(html_content, "text/html")
        msg.send(fail_silently=False)
        logger.info(f"[Email Success] Password reset code sent to {to_email}")
    except Exception as e:
        logger.error(f"[Email Error] Failed to send password reset email to {to_email}: {e}")

