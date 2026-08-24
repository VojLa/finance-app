# Cash-flow testing

| Risk | Layer | Evidence |
| --- | --- | --- |
| Duplicate canonical write | service/integration | transaction idempotency tests |
| Invalid category hierarchy | service/API | category cycle and access tests |
| Mixed operational/finance state | projection/frontend | operational dashboard tests |
