// 术语表：零基础学生看到的专业词，悬停给一句大白话解释。
// key 用小写，匹配时大小写不敏感。
export const GLOSSARY = {
  indexerror: '“下标越界”错误：你访问了列表里不存在的位置，比如只有 3 个元素却去取第 4 个。',
  typeerror: '“类型错误”：对不匹配的类型做了操作，比如拿数字和字符串相加。',
  keyerror: '“键不存在”错误：去字典里取一个根本没存进去的 key。',
  valueerror: '“值不合法”错误：类型对，但内容超出了函数能接受的范围或格式。',
  zerodivisionerror: '“除以零”错误：某一步把 0 当成了除数。',
  nameerror: '“名字未定义”：用了一个还没定义过的变量名（常因拼写或忘了赋值）。',
  attributeerror: '“属性不存在”：在对象上访问了它没有的属性，常见于变量其实是 None。',
  nullpointerexception: 'Java 里的“空指针”：在一个还是空（null）的对象上调方法或取属性。',
  traceback: '“报错栈”：Python 出错时打印的调用路径，自下而上记录了出错经过——最后一行通常是关键。',
  下标: '列表中元素的位置编号，从 0 开始。长度为 n 的列表，合法下标是 0 到 n-1。',
  索引: '同“下标”：列表中元素的位置编号，从 0 开始。',
  越界: '访问了超出合法范围的下标，比如列表只到下标 2，你却访问了下标 3。',
  none: 'Python 表示“什么都没有/空值”的特殊值。在 None 上取属性或调方法就会报错。',
  range: 'Python 生成一串数字的工具：range(3) 产生 0、1、2（不含 3），常用来控制循环次数。',
  迭代: '循环时一轮一轮地处理，每一轮叫一次迭代。',
  边界: '输入的极端情况：空列表、单个元素、最大/最小值——最容易暴露 Bug 的地方。',
  根因: '问题的真正原因（“为什么错”），而不只是表面的改法。',
  断点: '让程序运行到某一行暂停下来，方便检查当时各变量的值。',
  内化: '不只是修好，还能复述成因、举一反三——知识点真正变成你自己的。',
  防御式编程: '提前考虑空值、异常输入等情况，主动加判断，让代码不容易崩。',
  迁移: '把这次学到的东西用到新的、类似的问题上。',
  // 知识点词（题目里会用到，悬停给零基础一句解释）
  二维数组: '“数组里装数组”，像表格一样有行有列，用两个下标定位一个元素。',
  数组: '一串按顺序排列的元素，用下标（从 0 开始）访问每一个。',
  字符串: '一串字符（文字），本质上也是按下标排列的序列。',
  字典: '用“键→值”存取数据的结构，靠键来查值，键不存在就会报 KeyError。',
  集合: '一堆不重复元素的容器，常用来判断“在不在里面”。',
  嵌套循环: '循环里面再套一层循环，容易把内外层的变量搞混。',
  循环不变式: '循环每一轮都应保持成立的规律，用来检查循环逻辑对不对。',
  循环: '让一段代码重复执行多次，次数由条件或 range 控制。',
  迭代器: '一种“按需逐个取出元素”的对象，取完就没了。',
  控制流: '程序执行的先后顺序：哪段先跑、哪段被跳过、哪段重复。',
  数据流追踪: '跟着一个变量的值一步步走，看它在哪一步变成了出错的样子。',
  函数返回值: '函数算完后交出去的结果；忘了 return 就会得到 None。',
  函数默认参数: '调用函数时没传就用预设值的参数（默认值若是可变对象要小心坑）。',
  Optional处理: '处理“可能有、也可能是 None”的值，用前先判断它是不是空。',
  对象生命周期: '对象从创建到不再使用的过程；在它还没创建好时用它就会出错。',
  二分查找: '在有序数据里每次砍掉一半范围来快速查找，边界条件最容易写错。',
  API契约: '一个函数/接口承诺的输入输出规则，双方都要遵守。',
}

// 把一段文本里命中的术语包成 <span class="term">，返回 [{text, term?}] 片段列表。
// 只匹配整词边界附近的术语，长词优先，避免“range”误伤“orange”等。
export function annotate(text) {
  if (!text) return [{ text: '' }]
  const keys = Object.keys(GLOSSARY).sort((a, b) => b.length - a.length)
  const segments = [{ text }]
  for (const key of keys) {
    const def = GLOSSARY[key]
    for (let i = 0; i < segments.length; i++) {
      const seg = segments[i]
      if (seg.term) continue // 已标注的片段不再拆
      const lower = seg.text.toLowerCase()
      const at = lower.indexOf(key)
      if (at === -1) continue
      const before = seg.text.slice(0, at)
      const hit = seg.text.slice(at, at + key.length)
      const after = seg.text.slice(at + key.length)
      const replacement = []
      if (before) replacement.push({ text: before })
      replacement.push({ text: hit, term: def })
      if (after) replacement.push({ text: after })
      segments.splice(i, 1, ...replacement)
      i += replacement.length - 1
    }
  }
  return segments
}
