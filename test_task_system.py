import shutil
from agent.task_system import create_task, claim_task, complete_task, list_tasks, can_start, get_task_json, load_task
from agent.config import TASKS_DIR

if TASKS_DIR.exists():
    shutil.rmtree(TASKS_DIR)
    TASKS_DIR.mkdir()

print("=== 测试1: 创建任务 ===")
t1 = create_task("Task 1", "First task")
print(f"Created: {t1.id}")
print(f"ID格式正确: {t1.id.startswith('task_')}")
print(f"Status: {t1.status}")
print(f"Owner: {t1.owner}")

print("\n=== 测试2: get_task_json ===")
json_str = get_task_json(t1.id)
print(f"JSON格式正确: {'id' in json_str and 'subject' in json_str}")

print("\n=== 测试3: claim_task ===")
result = claim_task(t1.id, "agent1")
print(f"Claim结果: {result}")
t1_loaded = load_task(t1.id)
print(f"Status after claim: {t1_loaded.status}")
print(f"Owner after claim: {t1_loaded.owner}")

print("\n=== 测试4: 重复认领 ===")
result2 = claim_task(t1.id, "agent2")
print(f"重复认领结果: {result2}")
print(f"正确阻止: {'already owned' in result2}")

print("\n=== 测试5: complete_task ===")
result3 = complete_task(t1.id)
print(f"Complete结果: {result3}")
t1_loaded = load_task(t1.id)
print(f"Status after complete: {t1_loaded.status}")

print("\n=== 测试6: 依赖关系 ===")
t2 = create_task("Task 2", "Second task", blockedBy=[t1.id])
print(f"Created task 2 with dependency on task 1")
print(f"can_start(t2) when t1 completed: {can_start(t2.id)}")

print("\n=== 测试7: 依赖未完成时不能认领 ===")
t3 = create_task("Task 3", "Third task")
t4 = create_task("Task 4", "Fourth task", blockedBy=[t3.id])
result4 = claim_task(t4.id)
print(f"认领被依赖未完成的任务: {result4}")
print(f"正确阻止: {'Cannot start' in result4}")

print("\n=== 测试8: complete_task 返回 unblocked ===")
claim_task(t3.id)
result5 = complete_task(t3.id)
print(f"Complete结果: {result5}")
print(f"包含Unblocked: {'Unblocked' in result5}")

print("\n=== 测试9: list_tasks ===")
tasks = list_tasks()
print(f"任务数量: {len(tasks)}")
print(f"正确数量: {len(tasks) == 4}")

print("\n=== 测试10: 非pending状态不能认领 ===")
t5 = create_task("Task 5")
claim_task(t5.id)
result6 = claim_task(t5.id)
print(f"非pending认领结果: {result6}")
print(f"正确阻止: {'cannot claim' in result6}")

print("\n=== 测试11: 非in_progress状态不能完成 ===")
t6 = create_task("Task 6")
result7 = complete_task(t6.id)
print(f"非in_progress完成结果: {result7}")
print(f"正确阻止: {'cannot complete' in result7}")

print("\n=== 所有测试通过! ===")
