"""
Hybrid local + cloud LLM example.

Pattern: Try the local model first (free, private, fast).
Optionally get a "second opinion" from ChatGPT (cloud) for comparison
or when you want higher-quality output.
"""

import os
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

load_dotenv()  # reads OPENAI_API_KEY from .env

# --- Local model (runs on your RTX 3060) ---
local_llm = ChatOllama(
    model="qwen2.5:14b",
    base_url="http://localhost:11434",
    temperature=0.7,
)

# --- Cloud model (OpenAI ChatGPT) ---
cloud_llm = ChatOpenAI(
    model="gpt-4o-mini",
    api_key=os.environ.get("OPENAI_API_KEY"),
    temperature=0.7,
)


def ask_local(question: str) -> str:
    response = local_llm.invoke(question)
    return response.content


def ask_cloud(question: str) -> str:
    response = cloud_llm.invoke(question)
    return response.content


def hybrid_ask(question: str, get_second_opinion: bool = False):
    print(f"Question: {question}\n")

    print("--- Local model (Qwen2.5:14b) ---")
    local_answer = ask_local(question)
    print(local_answer)

    if get_second_opinion:
        print("\n--- Cloud model (ChatGPT) second opinion ---")
        cloud_answer = ask_cloud(question)
        print(cloud_answer)


if __name__ == "__main__":
    # Try a simple question locally only
    hybrid_ask("What are three benefits of running LLMs locally?", get_second_opinion=False)

    print("\n" + "=" * 60 + "\n")

    # Try a harder question with both local and cloud for comparison
    hybrid_ask(
        "Explain the tradeoffs between local and cloud LLMs for a small business, in 3 sentences.",
        get_second_opinion=True,
    )
