from fastapi import FastAPI
import os
from dotenv import load_dotenv
from groq import Groq
import asyncio
import uvicorn
import json
from yt_dlp import YoutubeDL
from functools import reduce
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, VideoUnavailable
from googleapiclient.discovery import build

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
app = FastAPI()


def getYoutubeContent(topic):
    print("🚀 ~ topic ======>:", topic)
    
    # Check if RAG system already has this topic
    from langchain.vectorstores.chroma import Chroma
    from get_embedding_function import get_embedding_function
    
    try:
        db = Chroma(persist_directory="chroma", embedding_function=get_embedding_function())
        results = db.similarity_search_with_score(topic, k=5)
        print(len(results),"result")
        if results and results[0][1] < 0.7:  # Lower score means higher similarity
            print("✅ Found similar content in RAG system, returning cached result.")
            cached_videos = []
            for doc, score in results:
                cached_videos.append({
                        'title': doc.metadata.get('title', ''),
                        'description': doc.metadata.get('description', ''),
                        'transcript': doc.page_content,
                        'video_id': doc.metadata.get('video_id', ''),
                        'url': doc.metadata.get('url', ''),
                        'thumbnail': doc.metadata.get('thumbnail', ''),
                    })
            print(len(cached_videos),"cached_videos")
            if cached_videos:
                return cached_videos
    except Exception as e:
        print(f"⚠️ Error checking RAG system: {e}")
    
    # If not found in RAG, proceed with YouTube search
    youtube = build('youtube', 'v3', developerKey=os.getenv("YOUTUBE_API_KEY"))
    search_response = youtube.search().list(
        q=topic,
        part='snippet',
        type='video',
        maxResults=2,
        order='relevance',
    ).execute()

    videos = []
    for search_result in search_response.get('items', []):
        video_id = search_result['id']['videoId']
        # Try fetching transcript
        transcript_data = None
        ytt_api = YouTubeTranscriptApi()
        try:
            transcript = ytt_api.list(video_id).find_transcript(['en'])
            expected_transcript = transcript.fetch()
            if hasattr(expected_transcript, "snippets"):
                data = (" ".join(s.text.strip()
                        for s in expected_transcript.snippets if s.text.strip()))
                transcript_data = data

        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
            # 1. Download audio
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'{video_id}.%(ext)s',  # filename
                'quiet': True,
            }
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])

            audio_file = f"./{video_id}.webm"
            with open(audio_file, "rb") as f:
                transcription = client.audio.transcriptions.create(
                    file=f,  # Pass file object, not string
                    model="whisper-large-v3-turbo",
                    prompt="Specify context or spelling and response must be translate in English",  # Optional
                    language="en",
                    response_format="json",
                    temperature=0.0
                )
            transcript_data = transcription.text

            # Remove audio file after transcription
            if os.path.exists(audio_file):
                os.remove(audio_file)
            print(f"⚠ 🚀 ~  No transcript available for 🚀 ~  {video_id}")
        except Exception as e:
            print(f"⚠ 🚀 ~  Error fetching transcript for 🚀 ~  {video_id}: {e}")
            transcript_data = []
            return "Error fetching transcript for video: " + str(e)

        videos.append({
            'title': search_result['snippet']['title'],
            'description': search_result['snippet']['description'],
            'transcript': transcript_data,
            'video_id': video_id,
            'url': f"https://www.youtube.com/watch?v={video_id}",
            'thumbnail': search_result['snippet']['thumbnails']['default']['url'],
        })

        # Add to RAG system for future queries
        try:
            from langchain.schema.document import Document
            from langchain.vectorstores.chroma import Chroma
            from get_embedding_function import get_embedding_function
            
            db = Chroma(persist_directory="chroma", embedding_function=get_embedding_function())
            
            # Create document with video content
            doc = Document(
                page_content=transcript_data,
                metadata={
                    "title": search_result['snippet']['title'],
                    "description": search_result['snippet']['description'],
                    "video_id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "thumbnail": search_result['snippet']['thumbnails']['default']['url'],
                    "source": "youtube",
                    "topic": topic,
                    "id": f"youtube:{video_id}:0"
                }
            )
            
            # Check if this video already exists in the database
            existing_items = db.get(include=[])
            existing_ids = set(existing_items["ids"])
            
            if doc.metadata["id"] not in existing_ids:
                db.add_documents([doc], ids=[doc.metadata["id"]])
                db.persist()
                print(f"✅ Added video {video_id} to RAG system")
            else:
                print(f"📋 Video {video_id} already exists in RAG system")
                
        except Exception as e:
            print(f"⚠️ Error adding to RAG system: {e}")

    # print("🚀 ~ videos ======>:", videos)
    # print("transcript_data ==>:", transcript_data)
    return videos


@app.get("/youtube-content")
async def youtube_content(prompt: str):
    messages = [
        {
            "role": "system",
            "content": """You are an expert content quality evaluator for YouTube videos.

Your task is to:
evaluate only the videos retrieved from the tools (do not search or generate new videos). 
Evaluate each unique video topic only once — do not repeat the same topic.
1. Analyze the content of each video, including its transcript.
2. Score the content quality on a scale of 1 to 10, where 1 is the lowest quality and 10 is the highest quality.
3. Provide a short explanation of your score, including strengths and weaknesses of the content and its relevance to the topic.
4. Provide a details summary (1-5 sentences) of the content.

You have access to the following tools:
1. getYoutubeContent(topic) - to get the content of YouTube videos including transcript, title, description, etc.

Return an **array of JSON objects**, one object per unique video:
[
  {
    "aiScore": number,
    "summary": "short explanation with important points of the content",
    "reason": "detailed explanation of the score, strengths and weaknesses of the content",
    "title": "Video title",
    "description": "Video description",
    "video_id": "Video id",
    "url": "Video URL",
    "thumbnail": "Video thumbnail"
  }
]

Do not include anything outside this array. Only evaluate the videos provided by the tools.
"""
        }
    ]

    messages.append({
        "role": "user",
        "content": prompt
    })

    while True:
        completion = await asyncio.to_thread(lambda: client.chat.completions.create(
            messages=messages,
            model="llama3-70b-8192",
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "getYoutubeContent",
                        "description": "Get the content of a YouTube video by topic. here you must be get transcript, title , description.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "topic": {
                                    "type": "string",
                                    "description": "The topic of the YouTube video that use for search on youtube and get content."
                                },
                            },
                            "required": ["topic"]
                        }
                    }
                },
            ]
        ))

        messages.append(completion.choices[0].message)

        tool_calls = completion.choices[0].message.tool_calls

        # Exit loop if no tool call
        if not tool_calls:
            break

        for tool in tool_calls:
            function_name = tool.function.name
            function_args = json.loads(tool.function.arguments)

            if function_name == "getYoutubeContent":
                result = getYoutubeContent(
                    topic=function_args["topic"]
                )
                print(len(result),"result in getYoutubeContent")
            # Append tool output for next AI step
            messages.append({
                "role": "tool",
                "tool_call_id": tool.id,
                "content": json.dumps(result)
            })
          
    # print("🚀 ~ messages ======>:", messages)
    parsed_content = json.loads(messages[-1].content)
    # print("🚀 ~ messages ======>:", parsed_content)
    return {"assistant": parsed_content}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)