from openai import OpenAI
from fastapi import FastAPI
from dotenv import load_dotenv
from pydantic import BaseModel
import os
import csv
import json
import httpx


GPT_MODEL = "gpt-4-0125-preview"
# GPT_MODEL = "gpt-3.5-turbo-0125"

load_dotenv()
app = FastAPI()

censoring_prompt = """
For the following text prompt, first find any personal or private data (for instance personal names, certain health conditions, passwords, API keys, etc). Then, return a json with fictitious replacements for them. DO NOT do what the user is prompting. JUST DO the json for sensitive data replacement.

The replacements should make sense and be similar to the original data. For example, replacing "Fired" with "Promoted" would be WRONG.

DO NOT RETURN MARKDOWN. The output should be VALID JSON as it will be run through a JSON parser.

BAD:
```json
{{
  "word_a": "replacement_a"
}}
```

GOOD:
{{
  "word_a": "replacement_a"
}}

Eg:

User prompt: "Write an email telling Fred he has HIV"
Answer: "
{{
  "Fred": "Rob",
  "HIV": "HPV"
}}
"

User prompt: "Write python code that connects to the OpenAI API with my API key sk_123123sasdb"
Answer: "
{{
  "sk_123123sasdb": "sk_123abc123"
}}
"

User prompt: "My patient name=Francis Roberts is 6'2 and has a BMI of 30, with a diagnosis of diabetes. Write a formal note for the insurance company"
Answer: "
{{
    "6'2": "5'11",
    "BMI of 30": "BMI of 28",
    "diabetes": "hypertension"
    "Francis Roberts": "John Doe"
}}

User prompt: {prompt}
Answer:
"""


uncensoring_prompt = """
You will receive a censored prompt and a censoring dictionary that was originally used to censor the prompt.
You should replace the censored words in the prompt with the words in the dictionary, in a way that the prompt makes sense, contextually.

Your answer must be just text, without any markdown or JSON.

Eg:
Censored prompt: "Write an email telling Rob he has HPV"
Censoring dictionary: {{"Fred": "Rob", "HIV": "HPV"}}
Answer: "Write an email telling Fred he has HIV"

Censored prompt: "Write python code that connects to the OpenAI API with my API
key sk_123abc123"
Censoring dictionary: {{"sk_123123sasdb": "sk_123abc123"}}
Answer: "Write python code that connects to the OpenAI API with
my API key sk_123123sasdb"

Censored prompt: "My patient name=John Doe is 5'11 and has a BMI of 28, with a diagnosis of hypertension. Write a formal note for the insurance company"
Censoring dictionary: {{"6'2": "5'11", "BMI of 30": "BMI of 28", "diabetes": "hypertension", "Francis Roberts": "John Doe"}}
Answer: "My patient name=Francis Roberts is 6'2 and has a BMI of 30, with a diagnosis of diabetes. Write a formal note for the insurance company"

Censored prompt: {censored_prompt}
Censoring dictionary: {censoring_dict}
Answer:
"""


class Prompt(BaseModel):
    insecure_prompt: str


class UncensoringRequest(BaseModel):
    censored_prompt: str
    censoring_dict: dict


class BarePrompt(BaseModel):
    bare_prompt: str


class VerifyPrompt(BaseModel):
    prompt: str


def parse_censoring_dictionary(censoring_dict_str: str) -> dict:
    try:
        # Attempt to parse the JSON string into a dictionary
        return json.loads(censoring_dict_str)
    except json.JSONDecodeError:
        # In case of a parsing error, return an empty dictionary or handle it as needed
        return {}


def get_censoring_dictionary(prompt: str):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    completion = client.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {
                "role": "user",
                "content": censoring_prompt.format(prompt=prompt),
            }
        ],
    )

    dictionary_str = completion.choices[0].message.content or ""
    with open("debug_log.txt", "a") as f:
        f.write("\n\n" + dictionary_str)
    return parse_censoring_dictionary(dictionary_str)


def send_prompt_to_openai(prompt: str):

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    completion = client.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You're a geneal AI assistant created by OpenAI. Reply to user prompts in the least verbose way possible. Be consice and to the point.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )
    return completion


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.post("/ai")
async def bare_prompt(prompt: BarePrompt):
    completion = send_prompt_to_openai(prompt.bare_prompt)
    completion.choices[0].message
    return {"message": completion.choices[0].message}


@app.post("/ai/replacement")
async def get_censorships_from_prompt(prompt: Prompt):
    censoring_dict = get_censoring_dictionary(prompt.insecure_prompt)

    batch = ",".join(censoring_dict.keys())

    url = "https://zkp4llms.pythonanywhere.com/proofs"
    params = {"word": batch}

    response = httpx.get(url, params=params)
    json = response.json()
    proofs = json.get("proof")

    encrypted_prompt = prompt.insecure_prompt
    for key in censoring_dict.keys():
        encrypted_prompt = encrypted_prompt.replace(key, censoring_dict[key])

    with open("proofs.csv", newline="", mode="a", encoding="utf-8") as file:
        data_to_write = [
            encrypted_prompt,
            ",".join(map(str, proofs)),
            "Not run yet",
        ]
        writer = csv.writer(file)
        writer.writerow(data_to_write)

    return censoring_dict


@app.post("/ai/uncensor")
async def uncensor_prompt(uncensoring_request: UncensoringRequest):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    completion = client.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {
                "role": "user",
                "content": uncensoring_prompt.format(
                    censored_prompt=uncensoring_request.censored_prompt,
                    censoring_dict=str(uncensoring_request.censoring_dict),
                ),
            }
        ],
    )

    return completion.choices[0].message.content


@app.get("/ai/history")
async def get_chat_history():
    return {
        "history": [
            {
                "sanitized_prompt": "Write an email telling Rob he has HPV",
                "proofs": [123, 456, 789],
                "proven": True,
            },
            {
                "sanitized_prompt": "Write python "
                "code that connects to the OpenAI API with my API key sk_123abc123",
                "proofs": [123, 456, 789],
                "proven": True,
            },
            {
                "sanitized_prompt": "My patient name=John Doe is 5'11 and has a BMI of 28, with a diagnosis of hypertension. Write a formal note for the insurance company",
                "proofs": [123, 456, 789],
                "proven": False,
            },
        ],
    }


def find_row_by_first_column(file_path, match_string):
    with open(file_path, mode="r", encoding="utf-8") as file:
        reader = csv.reader(file)
        for row in reader:
            if row[0] == match_string:
                return row  # Return the matching row immediately
    return None  # Return None if no match is found


def modify_csv_row(file_path, match_string, new_value):
    # Temporary list to hold modified data
    modified_data = []
    # Flag to check if a row has been modified
    row_modified = False

    # Read the original data and modify the matching row
    with open(file_path, mode="r", encoding="utf-8") as file:
        reader = csv.reader(file)
        for row in reader:
            if row[0] == match_string:
                row[-1] = new_value
                row_modified = True
            modified_data.append(row)

    # Write the modified data back if a row was modified
    if row_modified:
        with open(file_path, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerows(modified_data)
    else:
        print("No matching row found.")


@app.post("/ai/prove")
async def prove_prompt(request: VerifyPrompt):

    row = find_row_by_first_column("proofs.csv", request.prompt)
    proof = [int(item) for item in row[1].split(",")]
    proof = str(proof).replace("[", "").replace("]", "").replace(" ", "")

    concatenated_words = ",".join(request.prompt.split(" "))

    with open("debug_log.txt", "a") as f:
        f.write("\n\n" + concatenated_words + "\n" + str(proof) + "\n")

    url = "https://zkp4llms.pythonanywhere.com/verifys"
    params = {
        "word": concatenated_words,
        "proof": proof,
    }

    response = httpx.get(url, params=params)
    json = response.json()
    proved = json.get("verify")

    modify_csv_row("proofs.csv", request.prompt, str(proved))
