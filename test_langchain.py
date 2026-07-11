"""
Quick test script to confirm LangChain can talk to the local Ollama server.
"""

from langchain_ollama import ChatOllama

def main():
    # Point at the local Ollama server
    llm = ChatOllama(
        model="qwen2.5:14b",
        base_url="http://localhost:11434",
        temperature=0.7,
    )

    print("Sending test prompt to qwen2.5:14b via LangChain...\n")

    response = llm.invoke("In one sentence, what is LangChain used for?")

    print("Response:")
    print(response.content)

if __name__ == "__main__":
    main()
