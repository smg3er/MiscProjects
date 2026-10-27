from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os

# ================== НАСТРОЙКИ ==================
CREDENTIALS_PATH = r"C:\Users\smg3e\Downloads\client_secret_929140227426-ki7juieh0319t39n6m4opmpv80dasg9i.apps.googleusercontent.com.json"  # ← поменяй путь, если файл лежит в другом месте
FOLDER_ID = "1vMAcWOH4K6_7FcsfKf8Hi5BF2FHxrcLC"

# ===============================================

# Авторизация через OAuth (первый раз откроет браузер)
flow = InstalledAppFlow.from_client_secrets_file(
    CREDENTIALS_PATH,
    scopes=['https://www.googleapis.com/auth/drive']
)

credentials = flow.run_local_server(port=0)  # автоматически откроет браузер

service = build('drive', 'v3', credentials=credentials)

print("✅ Подключение к Google Drive через OAuth успешно\n")


# 1. Показать файлы в папке
def list_files():
    results = service.files().list(
        q=f"'{FOLDER_ID}' in parents",
        fields="files(id, name, mimeType, size)"
    ).execute()

    files = results.get('files', [])
    print(f"В папке найдено {len(files)} файлов:")
    for f in files:
        size = f.get('size', '—')
        print(f"• {f['name']}  ({size} байт)")


# 2. Загрузить файл
def upload_file(local_path, file_name=None):
    if file_name is None:
        file_name = os.path.basename(local_path)

    file_metadata = {
        'name': file_name,
        'parents': [FOLDER_ID]
    }

    media = MediaFileUpload(local_path, resumable=True)

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id, name'
    ).execute()

    print(f"✅ Загружен: {file.get('name')} (ID: {file.get('id')})")


# ================== ЗАПУСК ==================
if __name__ == "__main__":
    list_files()

    # Пример загрузки файла (раскомментируй когда нужно):
    upload_file(r"C:\Users\smg3e\OneDrive\Рабочий стол\test.txt", "Мой тестовый файл.txt")
    # upload_file(r"C:\Users\smg3e\velo_business_plan.md")