"""Offline test of Table charts and date filters. Scripted replies, no network."""
from src.agent.agent import answer
from src.agent.llm import FakeProvider
from src.agent.schema import build_schema
from src.answer_text import summarize

USER = {"username": "leadership1", "role": "LEADERSHIP", "row_scope": "ALL"}
schema = build_schema(USER)

OCT = ('{"reasoning":"Total planned for October","table":"PRODUCTION_ORDERS","chart":"Table","x":null,'
       '"group_by":[],"measures":[{"column":"QTY_PLANNED","agg":"Sum"}],"color":null,"bucket":null,'
       '"filters":[],"date_filters":[{"column":"TARGET_DATE","year":null,"month":10,"from":null,"to":null}]}')
MULTI = ('{"reasoning":"Planned and built by month, plant and engine model","table":"PRODUCTION_ORDERS",'
         '"chart":"Table","x":null,"group_by":["TARGET_DATE","PLANT","ENGINE_MODEL"],'
         '"measures":[{"column":"QTY_PLANNED","agg":"Sum"},{"column":"QTY_BUILT","agg":"Sum"}],'
         '"color":null,"bucket":"Month","filters":[],"date_filters":[]}')

for name, reply in [("quantity planned for october", OCT), ("planned and built by month, plant, engine", MULTI)]:
    print("\n" + "=" * 70 + "\nQ:", name)
    res = answer(USER, name, FakeProvider([reply]), schema)
    print("status:", res["status"])
    if res["status"] != "ok":
        print(res)
        continue
    print("sql:", res["sql"])
    print(res["df"].head(6).to_string(index=False))
    print("-- written answer --")
    for line in summarize(res):
        print(" *", line)
