When working from a feature-request issue, treat its human approval checkboxes as gates:

- Do not implement until **Design approved** is checked by a human. If it is unchecked, provide the design for review and stop.
- After implementation, run `docker compose run --rm test` and `docker compose run --rm browser-test`, then report results and remaining risks. Stop until **Test results reviewed** is checked by a human.
- Do not create a pull request until **Pull request creation approved** is checked by a human.
- Never check approval boxes yourself or infer approval from assignment or passing tests.

Keep changes within the approved issue scope. After tests pass, build and start the current checkout with `docker compose up --build --detach --wait api`, verify health and `http://localhost:8000/`, leave the preview running, and report the result. Do not stop or replace an app from another checkout if port 8000 is occupied.
