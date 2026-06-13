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

// 语法砖块：比知识点更底层的"代码符号"，给完全没见过代码的人扫盲。
// match：用来判断这段代码里有没有出现这个砖块（出现才展示，做到「贴着本题代码」）。
export const SYNTAX_BRICKS = [
  { name: 'def（定义函数）', match: (c) => /\bdef\b/.test(c),
    desc: '定义一段可以反复使用的代码，并给它起个名字。例：def total(arr): 就是定义一个叫 total 的函数。' },
  { name: '( ) 圆括号', match: (c) => c.includes('('),
    desc: '跟在某个名字后面，表示"使用/调用它"，里面放它要处理的东西（叫"参数"）。例：total(arr) 里的 arr。' },
  { name: 'len( )（数个数 / 长度）', match: (c) => /\blen\(/.test(c),
    desc: '数一数里面有几个，给出"长度"。例：len("hello") 是 5，len([1,2,3]) 是 3。注意：下标从 0 开始，所以最后一个的下标是"长度减 1"。' },
  { name: ': 冒号', match: (c) => /:/.test(c),
    desc: '意思是"下面缩进的这几行，归我管"。def、for、while、if 后面都要跟一个冒号。' },
  { name: '缩进（行首空格）', match: (c) => /\n[ \t]+\S/.test(c),
    desc: 'Python 靠每行开头的空格分清层次——缩进对齐的几行，属于它们上面那一行。' },
  { name: '= 赋值', match: (c) => /[^=!<>]=[^=]/.test(c),
    desc: '把右边的值存进左边的名字里。例：s = 0 让 s 这个名字代表 0。（注意：这不是数学的"相等"）' },
  { name: 'return（返回结果）', match: (c) => /\breturn\b/.test(c),
    desc: '把函数算好的结果"交出去"。没有 return，函数就等于没给结果（返回 None）。' },
  { name: 'for … in range(…)（循环）', match: (c) => /\bfor\b/.test(c),
    desc: '重复执行一段代码若干次。range(3) 会让它跑 3 次，每次的编号是 0、1、2。' },
  { name: 'while 条件（循环）', match: (c) => /\bwhile\b/.test(c),
    desc: '只要条件还成立，就一直重复，直到条件不成立才停。' },
  { name: 'if 条件（判断）', match: (c) => /\bif\b/.test(c),
    desc: '如果条件成立，就执行下面缩进的代码；不成立就跳过。' },
  { name: '[ ] 方括号 / 下标', match: (c) => c.includes('['),
    desc: '方括号是"列表"（一串东西）；arr[0] 表示取列表里第 0 个（也就是第一个）。' },
  { name: '.append( )（往列表加东西）', match: (c) => c.includes('.append'),
    desc: '往列表的末尾加一个新元素。例：arr.append(5) 把 5 加到 arr 后面。' },
  { name: '.get( )（按键取值）', match: (c) => c.includes('.get('),
    desc: '从字典里按"键"取出对应的值；取不到时返回 None（而不是直接报错）。' },
  { name: 'print( )（打印）', match: (c) => /\bprint\(/.test(c),
    desc: '把括号里的东西显示出来，方便你看到程序算出了什么。' },
  { name: '# 注释', match: (c) => /#/.test(c),
    desc: '井号后面是写给人看的说明，程序会自动忽略它，不影响运行。' },
  { name: 'None（空值）', match: (c) => /\bNone\b/.test(c),
    desc: '表示"什么都没有/空"。在 None 上调用方法或取属性会报错。' },
  { name: 'class（类）', match: (c) => /\bclass\b/.test(c),
    desc: '定义一种"对象的模板"，里面可以装数据和函数。例：class Student: 定义"学生"这种对象。' },
]

// 返回这段代码里实际出现的语法砖块（只讲它用到的，不堆砌）
export function bricksInCode(code) {
  if (!code) return []
  return SYNTAX_BRICKS.filter((b) => b.match(code))
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
