import json
import urllib.request
import uuid

# 1. Get guest token
req_guest = urllib.request.Request(
    "http://127.0.0.1:8000/api/v1/auth/guest",
    data=b"{}",
    headers={"Content-Type": "application/json"},
)
guest_data = json.loads(urllib.request.urlopen(req_guest).read().decode())
token = guest_data["access_token"]
ws_id = guest_data["workspace_id"]
print("Guest email:", guest_data["user"]["email"])
print("Guest workspace:", ws_id)

# 2. Upload text document with tokenization experiment
sample_text = """
Lab Experiment 1: Word and Character Tokenization with NLTK
Objective: Understand basic word and character splitting using traditional NLP libraries.
# Install requirement if needed: pip install nltk
import nltk
nltk.download('punkt')
from nltk.tokenize import word_tokenize, sent_tokenize
# Sample text
text = 'Artificial Intelligence, or AI, is transforming the world. Is it safe? Many wonder.'
# 1. Sentence Tokenization
sentences = sent_tokenize(text)
print(sentences)
# 2. Word Tokenization
words = word_tokenize(text)
print(words)
# 3. Character Tokenization
characters = list(text)
print(characters)
"""

boundary = "----WebKitFormBoundary" + uuid.uuid4().hex
body = (
    f"--{boundary}\r\n"
    f'Content-Disposition: form-data; name="file"; filename="Lab_Experiment_1.txt"\r\n'
    f"Content-Type: text/plain\r\n\r\n"
    f"{sample_text}\r\n"
    f"--{boundary}--\r\n"
).encode("utf-8")

upload_req = urllib.request.Request(
    f"http://127.0.0.1:8000/api/v1/workspaces/{ws_id}/documents",
    data=body,
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    },
)
upload_res = urllib.request.urlopen(upload_req)
doc_data = json.loads(upload_res.read().decode())
doc_id = doc_data["document_id"]
print("Uploaded document id:", doc_id)

# 3. Generate Grounded Quiz
quiz_payload = json.dumps({
    "count": 5,
    "difficulty": "medium",
    "document_ids": [doc_id],
}).encode("utf-8")

quiz_req = urllib.request.Request(
    f"http://127.0.0.1:8000/api/v1/workspaces/{ws_id}/study/quiz",
    data=quiz_payload,
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    },
)
quiz_res = urllib.request.urlopen(quiz_req)
quiz_data = json.loads(quiz_res.read().decode())
print("Generated quiz questions count:", len(quiz_data["questions"]))

for i, q in enumerate(quiz_data["questions"], 1):
    print(f"\nQ{i}: {q['stem']}")
    corr_idx = q["correct_answer_index"]
    for j, opt in enumerate(q["options"]):
        marker = "[X]" if j == corr_idx else "[ ]"
        print(f"   {marker} {chr(65+j)}. {opt}")
    print(f"   Quote: '{q['quote']}'")
