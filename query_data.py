import argparse
from langchain_chroma import Chroma
from langchain.prompts import ChatPromptTemplate
from langchain_ollama import OllamaLLM,ChatOllama

from get_embedding_function import get_embedding_function

CHROMA_PATH = "chroma"

PROMPT_TEMPLATE = """
Answer the question based only on the following context:

{context}

---

Answer the question based on the above context: {question}
"""


def main():
    # Create CLI.
    parser = argparse.ArgumentParser()
    parser.add_argument("query_text", type=str, help="The query text.")
    args = parser.parse_args()
    query_text = args.query_text
    query_rag(query_text)


def query_rag(query_text: str):
    # Prepare the DB.
    embedding_function = get_embedding_function()
    db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embedding_function)

    # Search the DB.
    results = db.similarity_search_with_score(query_text, k=5)

    context_text = "\n\n---\n\n".join([doc.page_content for doc, _score in results])
    prompt_template = ChatPromptTemplate.from_template(PROMPT_TEMPLATE)
    prompt = prompt_template.format(context=context_text, question=query_text)
    # print(prompt)

    model = ChatOllama(model="mistral:latest", streaming=True)
    response_text = model.stream(prompt)

    full_response = ""
    for chunk in response_text:
        content = chunk.content if hasattr(chunk, 'content') else str(chunk)
        print(content, end='', flush=True)
        full_response += content

    sources = [doc.metadata.get("id", None) for doc, _score in results]
    formatted_response = f"Response: {full_response}\nSources: {sources}"
    print(formatted_response)
    return formatted_response


if __name__ == "__main__":
    main()
