# Secrets checklist (Bill Automation Kit)

อย่า commit ไฟล์เหล่านี้ — มีใน `.gitignore` แล้ว

| ไฟล์ | วิธีได้ |
|------|---------|
| `.env` | `Copy-Item .env.example .env` แล้วกรอก |
| `page_token.json` | จาก Meta / Page Access Token — ดู `config_templates/page_token.example.json` |
| `no_api_send_bill/config/google_credentials.json` | Google Cloud → Service Account → JSON key |
| `auth.json` | รัน `save_auth_state.py` หลัง login Anousith (ถ้าใช้ถ่ายบิล) |
| `user_settings.json` | `config_templates/user_settings.example.json` (ngrok domain ฯลฯ) |
| `page_reply_config.json` | `config_templates/page_reply_config.example.json` |
| `no_api_send_bill/config/sheet_config.json` | `config_templates/sheet_config.example.json` |
| `no_api_send_bill/config/page_name_to_id.json` | `config_templates/page_name_to_id.example.json` |
| `no_api_send_bill_manual/config/*.json` | same templates as above (manual copy) |
| `browser_profile/` | login Facebook ครั้งแรกผ่าน Playwright |

ตรวจว่า **ไม่มีของคนอื่น** ติดอยู่ในโฟลเดอร์ก่อนแชร์เครื่อง / ก่อน `git add -A`
