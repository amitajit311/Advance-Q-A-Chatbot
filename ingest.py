#!/usr/bin/env python3
import os
import glob
from typing import List
from dotenv import load_dotenv
from multiprocessing import Pool
from tqdm import tqdm

from langchain.document_loaders import (
    CSVLoader,
    EverNoteLoader,
    PyMuPDFLoader,
    TextLoader,
    UnstructuredEmailLoader,
    UnstructuredEPubLoader,
    UnstructuredHTMLLoader,
    UnstructuredMarkdownLoader,
    UnstructuredODTLoader,
    UnstructuredPowerPointLoader,
    UnstructuredWordDocumentLoader,
    PyPDFLoader
)

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores import Chroma
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.docstore.document import Document

if not load_dotenv():
    print("Could not load .env file or it is empty. Please check if it exists and is readable.")
    exit(1)

from constants import CHROMA_SETTINGS
import chromadb

#  Load environment variables
persist_directory = os.environ.get('PERSIST_DIRECTORY')
source_directory = os.environ.get('SOURCE_DIRECTORY', 'source_documents')
embeddings_model_name = os.environ.get('EMBEDDINGS_MODEL_NAME')
print(embeddings_model_name, "embeddings_model_name")
chunk_size = 500
chunk_overlap = 50

# Map file extensions to document loaders and their arguments
LOADER_MAPPING = {
    ".csv": (CSVLoader, {}),
    # ".docx": (Docx2txtLoader, {}),
    ".doc": (UnstructuredWordDocumentLoader, {}),
    ".docx": (UnstructuredWordDocumentLoader, {}),
    ".enex": (EverNoteLoader, {}),
    # ".eml": (MyElmLoader, {}),
    ".epub": (UnstructuredEPubLoader, {}),
    ".html": (UnstructuredHTMLLoader, {}),
    ".md": (UnstructuredMarkdownLoader, {}),
    ".odt": (UnstructuredODTLoader, {}),
    # ".pdf": (PyMuPDFLoader, {}),
    ".pdf": (PyPDFLoader, {}),
    ".ppt": (UnstructuredPowerPointLoader, {}),
    ".pptx": (UnstructuredPowerPointLoader, {}),
    ".txt": (TextLoader, {"encoding": "utf8"}),
    # Add more mappings for other file extensions and loaders as needed
}


def load_single_document(file_path: str) -> List[Document]:
    ext = "." + file_path.rsplit(".", 1)[-1].lower()
    if ext in LOADER_MAPPING:
        loader_class, loader_args = LOADER_MAPPING[ext]
        loader = loader_class(file_path, **loader_args)
        return loader.load()

    raise ValueError(f"Unsupported file extension '{ext}'")


def load_documents(source_dir: str, ignored_files: List[str] = []) -> List[Document]:
    """
    Loads all documents from the source documents directory, ignoring specified files
    """
    all_files = []
    for ext in LOADER_MAPPING:
        all_files.extend(
            glob.glob(os.path.join(source_dir, f"**/*{ext.lower()}"), recursive=True)
        )
        all_files.extend(
            glob.glob(os.path.join(source_dir, f"**/*{ext.upper()}"), recursive=True)
        )
    filtered_files = [file_path for file_path in all_files if file_path not in ignored_files]

    with Pool(processes=os.cpu_count()) as pool:
        results = []
        with tqdm(total=len(filtered_files), desc='Loading new documents', ncols=80) as pbar:
            for i, docs in enumerate(pool.imap_unordered(load_single_document, filtered_files)):
                results.extend(docs)
                pbar.update()

    return results


def process_documents(ignored_files: List[str] = []) -> List[Document]:
    """
    Load documents and split in chunks
    """
    print(f"Loading documents from {source_directory}")
    documents = load_documents(source_directory, ignored_files)
    if not documents:
        print("No new documents to load")
        exit(0)
    print(f"Loaded {len(documents)} new documents from {source_directory}")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    texts = text_splitter.split_documents(documents)
    print(f"Split into {len(texts)} chunks of text (max. {chunk_size} tokens each)")

    return texts


def does_vectorstore_exist(db: Chroma, embeddings: HuggingFaceEmbeddings) -> bool:
    """
    Checks if vectorstore exists
    """
    try:
        # Try to get a sample embedding to check if the EmbeddingFunction interface is correct
        _ = embeddings("example text")
    except TypeError as e:
        if "got an unexpected keyword argument" in str(e):
            # The EmbeddingFunction interface has changed, and we need to adapt
            def new_embedding_function(input_text):
                return embeddings(input_text)

            db.set_embedding_function(new_embedding_function)

    if not db.get()['documents']:
        return False

    return True



# (Existing code remains the same...)

def main():
    # Create embeddings
    embeddings = HuggingFaceEmbeddings(model_name=embeddings_model_name)
    # Chroma client
    chroma_client = chromadb.PersistentClient(settings=CHROMA_SETTINGS, path=persist_directory)

    # Create Chroma instance
    db = Chroma(persist_directory=persist_directory, embedding_function=embeddings, client_settings=CHROMA_SETTINGS,
                client=chroma_client)

    if does_vectorstore_exist(db, embeddings):
        # Update and store locally vectorstore
        print(f"Appending to existing vectorstore at {persist_directory}")
        collection = db.get()
        texts = process_documents([metadata['source'] for metadata in collection['metadatas']])
        print(f"Creating embeddings. May take some minutes...")

        # Process documents in batches
        batch_size = 50  # Adjust the batch size as needed
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            db.add_documents(batch_texts)

    else:
        # Create and store locally vectorstore
        print("Creating new vectorstore")
        texts = process_documents()
        print(f"Creating embeddings. May take some minutes...")

        # Process documents in batches
        batch_size = 50  # Adjust the batch size as needed
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            db = Chroma.from_documents(batch_texts, embeddings, persist_directory=persist_directory,
                                       client_settings=CHROMA_SETTINGS, client=chroma_client)

    db.persist()
    db = None

    print(f"Ingestion complete! You can now run privateGPT.py to query your documents")

if __name__ == "__main__":
    main()




# def main():
#     # Create embeddings
#     embeddings = HuggingFaceEmbeddings(model_name=embeddings_model_name)
#     # Chroma client
#     chroma_client = chromadb.PersistentClient(settings=CHROMA_SETTINGS, path=persist_directory)
#
#     # Create Chroma instance
#     db = Chroma(persist_directory=persist_directory, embedding_function=embeddings, client_settings=CHROMA_SETTINGS,
#                 client=chroma_client)
#
#     if does_vectorstore_exist(db, embeddings):
#         # Update and store locally vectorstore
#         print(f"Appending to existing vectorstore at {persist_directory}")
#         collection = db.get()
#         texts = process_documents([metadata['source'] for metadata in collection['metadatas']])
#         print(f"Creating embeddings. May take some minutes...")
#         db.add_documents(texts)
#     else:
#         # Create and store locally vectorstore
#         print("Creating new vectorstore")
#         texts = process_documents()
#         print(f"Creating embeddings. May take some minutes...")
#         db = Chroma.from_documents(texts, embeddings, persist_directory=persist_directory,
#                                    client_settings=CHROMA_SETTINGS, client=chroma_client)
#
#     db.persist()
#     db = None
#
#     print(f"Ingestion complete! You can now run privateGPT.py to query your documents")

#
# if __name__ == "__main__":
#     main()

