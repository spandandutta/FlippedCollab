import os
import openai


# Need to set the OPENAI_API_KEY key as environment variable before starting the app

openai.api_key = os.getenv("OPENAI_API_KEY")


def get_summary_using_openai(input_text):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{
        "role": "user",
        "content": f"Summarize the following text with the most unique and helpful points, into a bulleted list of key points and takeaways: {input_text}"
        }],
        temperature=0
    )
    return response["choices"][0]["message"]["content"]


def run_question_answer(context, question):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{
        "role": "user",
        "content": f"Question answering:\nContext: {context}\nQuestion: {question}"
        }],
        temperature=0
    )
    return response["choices"][0]["message"]["content"]
