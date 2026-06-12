# Bug模式库设计 V0.2

> 职责：埋雷引擎的教学资产库。本文档给出编目规范、首批 15 个模式（boundary / null / loop 三类，对应 01 文档 MVP 范围）、以及配套的引导阶梯模板。

---

## 1. 编目规范

每个模式一个 YAML 文件，存放于 `patterns/<category>/<id>.yaml`，字段定义见 01 文档 2.1 节。入库前必须通过校验（第 4 节）。

ID 规则：`BP-<CATEGORY>-<序号>`，变式为 `BP-<CATEGORY>-<序号>-v<N>`。

每个模式必须回答三个教学问题：

1. **它考什么**：knowledge_points + capability_dims（与 04 注册表对齐）
2. **学生会看到什么**：symptom + 典型报错样例
3. **学会的标准是什么**：internalize_questions + variants

---

## 2. 首批模式清单（15个）

### 2.1 边界类（boundary，5个）

| ID | 名称 | 变换规则示例 | 症状 | 难度 | 知识点 |
|----|------|--------------|------|------|--------|
| BP-BOUNDARY-001 | 循环边界差一（off-by-one） | `i < n → i <= n` | RE | L1 | 数组、循环 |
| BP-BOUNDARY-002 | 空集合未防护 | 删除 `if (list.isEmpty()) return` | RE/WA | L2 | 集合、防御式编程 |
| BP-BOUNDARY-003 | 字符串下标越界 | `s.charAt(s.length())` | RE | L1 | 字符串 |
| BP-BOUNDARY-004 | 二维数组行列混淆 | `arr[j][i]` 替换 `arr[i][j]` | RE/WA | L2 | 二维数组 |
| BP-BOUNDARY-005 | 二分查找边界收缩错误 | `right = mid → right = mid - 1` 反向 | HANG/WA | L3 | 二分查找 |

### 2.2 空值类（null，5个）

| ID | 名称 | 变换规则示例 | 症状 | 难度 | 知识点 |
|----|------|--------------|------|------|--------|
| BP-NULL-001 | 对象未初始化即使用 | 删除 `obj = new X()` 行 | RE | L1 | 对象生命周期 |
| BP-NULL-002 | 方法返回null未检查 | 删除调用方的 null 判断 | RE | L2 | API契约 |
| BP-NULL-003 | Map取值未判空 | `map.get(k).foo()` 直接链式调用 | RE | L2 | Map、Optional |
| BP-NULL-004 | 报错位置≠根因位置 | 第30行漏赋值，第80行才崩 | RE | L3 | 调试、数据流追踪 |
| BP-NULL-005 | 字符串比较用== | `s.equals("x") → s == "x"` | WA/SILENT | L2 | 引用与值 |

### 2.3 循环类（loop，5个）

| ID | 名称 | 变换规则示例 | 症状 | 难度 | 知识点 |
|----|------|--------------|------|------|--------|
| BP-LOOP-001 | 循环变量未更新 | 删除 `i++` | HANG | L1 | 循环 |
| BP-LOOP-002 | while条件永真 | `while (x != 0)` 但x永不为0 | HANG | L2 | 循环不变式 |
| BP-LOOP-003 | 嵌套循环内层变量误用 | 内层用了外层的 `i` | WA | L2 | 嵌套循环 |
| BP-LOOP-004 | break/continue误用 | `continue` 替换 `break` | WA/HANG | L2 | 控制流 |
| BP-LOOP-005 | 遍历中修改集合 | 循环体内 `list.remove(x)` | RE/SILENT | L3 | 集合、迭代器 |

---

## 3. 完整条目示例

### 3.1 BP-BOUNDARY-001（L1 入门示例）

```yaml
id: BP-BOUNDARY-001
name: 循环边界差一错误（off-by-one）
category: boundary
languages: [java, python, c]
knowledge_points: [数组, 循环]
capability_dims: [Boundary_Awareness, Independent_Debug]
difficulty: L1
symptom: RE
symptom_sample: |
  Exception in thread "main" java.lang.ArrayIndexOutOfBoundsException:
  Index 3 out of bounds for length 3
    at Main.main(Main.java:12)
mutation_rule: "i < arr.length → i <= arr.length"
trigger_input: "任意非空数组"
root_cause_template: "循环条件包含了arr.length本身，最后一次迭代访问arr[length]，越过数组末尾"
fix_template: "将 <= 改为 <"
hint_ladder_ref: HL-BOUNDARY-001
internalize_questions:
  - "为什么 i <= arr.length 会越界？数组合法下标的范围是什么？"
  - "如果就是要访问最后一个元素，下标应该写什么？"
  - "以后写循环时，你会怎么快速自查边界？"
variants:
  - id: BP-BOUNDARY-001-v2
    scene: "字符串charAt遍历，i <= s.length()"
  - id: BP-BOUNDARY-001-v3
    scene: "从1开始累加到n，结果却用arr[n]取值"
```

### 3.2 BP-NULL-004（L3 进阶示例：报错位置≠根因位置）

```yaml
id: BP-NULL-004
name: 报错位置与根因位置分离的空指针
category: null
languages: [java]
knowledge_points: [对象生命周期, 数据流追踪]
capability_dims: [Root_Cause_Reasoning, Log_Reading, Hypothesis_Testing]
difficulty: L3
symptom: RE
symptom_sample: |
  java.lang.NullPointerException
    at UserService.login(UserService.java:80)   # 崩在这里
mutation_rule: "删除 UserService 构造器中第30行的 this.repo = repo 赋值"
trigger_input: "任意登录请求"
root_cause_template: "repo字段在构造时未赋值，第80行首次使用时为null——报错行只是案发现场，根因在30行"
fix_template: "在构造器中补回字段赋值"
hint_ladder_ref: HL-NULL-004
internalize_questions:
  - "为什么崩在80行，错却在30行？这两行是什么关系？"
  - "看到空指针，你应该先问'谁是null'还是'哪行崩了'？为什么？"
  - "怎么用日志或断点确认一个字段是从什么时候开始为null的？"
variants:
  - id: BP-NULL-004-v2
    scene: "依赖注入配置遗漏，service字段为null"
  - id: BP-NULL-004-v3
    scene: "缓存未命中返回null，三层调用之后才解引用"
```

> **教学价值说明**：L3 以上的模式重点考 `Root_Cause_Reasoning`——报错行与根因行分离，逼学生做"反向数据流追踪"而不是"盯着报错行改"。这类模式是从"会改错"到"会调试"的关键跳板。

---

## 4. 入库校验清单

每个模式入库前必须通过：

```text
□ ID/分类/难度符合编目规范
□ capability_dims 中的能力类型全部在 04 注册表中存在
□ hint_ladder_ref 指向的阶梯模板已存在（见第5节）
□ 带雷代码在 trigger_input 下确实触发 symptom（雷会响）
□ 其余测试用例全部通过（没有埋出多余的雷）
□ internalize_questions ≥ 2 个，variants ≥ 1 个
□ root_cause_template 由第二人复核语义准确（它是LLM判定归因一致性的标准答案，错了会污染事件）
```

最后一条最重要：**root_cause_template 同时是 AI 导师的 Ground Truth 和 `Root_Cause_Reasoning` 事件的评分基准**，它的质量直接决定画像数据的可信度。

---

## 5. 引导阶梯模板（HL-*）

每个模式配一份阶梯模板，导师 AI 按模板实例化（02 文档第 2 节）。示例：

```yaml
id: HL-BOUNDARY-001
pattern: BP-BOUNDARY-001
ladder:
  L0: "你用什么输入测试过？换几种长度的数组试试，什么时候会出错？"
  L1: "读一下异常信息：Index 3 out of bounds for length 3——它在告诉你什么？"
  L2: "问题在循环附近。你认为是：A. i的初始值  B. 循环条件  C. 数组声明？"
  L3: "数组长度为n时，合法下标是0到n-1。你的循环里i最大能取到几？"
  L4: "看第12行的循环条件。说说它为什么有问题？"
  L5: "讲解：条件i<=length使最后一次迭代访问arr[length]…（只讲思路，不给修复代码）"
```

模板编写规则：

- L0-L1 只能提问/指向现象，**禁止出现"边界""越界"等点破词**（点破词首次出现不得早于L2）
- L2 的选择题三个选项必须都"像真的"，错误选项来自该模式的常见误判
- L5 必须以"思路讲解"结尾，不得包含可粘贴的修复代码

---

## 6. MVP 范围与扩容路线

- MVP：上述 15 个模式 + 15 份阶梯模板，全部人工编写（模板题方式注入）
- V0.3：递归类、逻辑类入库；变换注入上线后，每个模式的 variants 由 mutation_rule 批量生成
- V0.4：SQL类、API类、资源类入库，配合 Vibe Coding 场景的 SILENT 雷（AI生成注入）
