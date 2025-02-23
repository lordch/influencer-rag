import json
import sys
import time
from datetime import timedelta

import config
import ragas_eval
from llm_model.llm_model_factory import get_llm_model
from model.rag_response import RagResponse
from vector_db import chroma_provider

chroma = chroma_provider.get_chroma()

llm_model = get_llm_model(config.model_name, config.local_models_path)


def read_full_movie_transcript(file_path, movie_title):
    with open(file_path, 'r') as file:
        movies = json.load(file)

    for movie in movies:
        if movie['title'] == movie_title:
            return movie['transcript']

    return None


def prepare_transcription_fragments(relevant_movie_chunks):
    movie_fragments_for_llm = []
    full_movies_already_added = []

    for movie_chunk in relevant_movie_chunks:
        document, score = movie_chunk

        if score < 0.5:
            movie_metadata = document.metadata

            if movie_metadata['istitle'] and (movie_metadata['title'] not in full_movies_already_added):
                movie_fragments_for_llm.append(
                    f"Movie title: '{movie_metadata['title']}', "
                    f"movie transcript: "
                    f"'{read_full_movie_transcript(movie_metadata['file'], movie_metadata['title'])}'; ")
                full_movies_already_added.append(movie_metadata['title'])
            elif not movie_metadata['istitle']:
                movie_fragments_for_llm.append(
                    f"Movie title: '{movie_metadata['title']}', "
                    f"movie transcript: '{document.page_content}'; ")

    if len(movie_fragments_for_llm) > 0:
        return movie_fragments_for_llm
    else:
        return None


def ask_question(users_query, enable_vector_search):
    query_start_time = time.time()

    if enable_vector_search:
        relevant_movie_chunks = chroma.similarity_search_with_score(users_query, 2)
        relevant_movies_list = prepare_transcription_fragments(relevant_movie_chunks)
        if relevant_movies_list is not None:
            relevant_movies = "\n".join(relevant_movies_list)
        else:
            relevant_movies = None
    else:
        relevant_movies = None

    if relevant_movies is not None:
        system = ("You'll get a question and a series of Youtube movie transcripts. "
                  "Each movie will contain the title and the relevant transcription fragment. "
                  "Base your answer only on the data coming from provided transcriptions and "
                  "make sure to always include the movie title in your answer."
                  f" List of movies: {relevant_movies}")
    else:
        system = ("First, say explicitly that you haven't found any relevant information "
                  "in the movie library. Then answer the following question "
                  "based on your knowledge.")

    llm_model_response = (
        llm_model.get_model_response(system, users_query))

    llm_user_response = llm_model_response.llm_user_response
    llm_full_response = llm_model_response.llm_full_response

    execution_time = time.time() - query_start_time

    if config.evaluations_enabled and enable_vector_search and llm_user_response:
        evaluation = ragas_eval.evaluate_question(users_query, relevant_movies_list, llm_user_response)
    else:
        evaluation = None

    return RagResponse(
        query=users_query,
        llm_user_response=llm_user_response,
        llm_full_response=llm_full_response,
        relevant_movie_chunks=relevant_movie_chunks,
        evaluation=evaluation,
        response_time=timedelta(seconds=execution_time)
    )


def print_response(response: RagResponse):
    if response.llm_user_response:
        print(f"Chatbot: '{response.llm_user_response}'; generated in {response.response_time}\n")
        if response.evaluation:
            print(response.evaluation)
    else:
        print("Error! No 'Answer' present in chatbot's response: ")


def main():
    if len(sys.argv) > 1:
        response = ask_question(sys.argv[1], True)
        print_response(response)
    else:
        print("Welcome to the chat. Type your query or one of the following commands:\n"
              "- 'response' to see the entire response of the previous query,\n"
              "- 'context' to see the context,\n"
              "- 'enable' to enable vector db search,\n"
              "- 'disable' to disable vector db search,\n"
              "- 'exit' to leave.\n")
        response = None
        vector_db_search_enabled = True

        while True:
            user_query = input("You: ").strip()

            if user_query.lower() == 'exit':
                print("Chatbot: Goodbye!")
                break
            elif user_query.lower() == 'response':
                print(response.llm_full_response, "\n")
            elif user_query.lower() == 'context':
                for chunk in response.relevant_movie_chunks:
                    document, score = chunk
                    print(f"- Content: '{document.page_content}' ({score})")
                    print(f"- Metadata: '{document.metadata}'\n")
            elif user_query.lower() == 'enable':
                vector_db_search_enabled = True
            elif user_query.lower() == 'disable':
                vector_db_search_enabled = False
            else:
                response = ask_question(user_query, vector_db_search_enabled)
                print_response(response)


if __name__ == "__main__":
    main()
