curl -X POST http://localhost:8000/search \
  -H "content-type: application/json" \
  -d '{
    "q": "python httpx tutorial",
    "k": 2
  }'
