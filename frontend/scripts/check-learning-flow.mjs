import assert from 'node:assert/strict'
import { LEARNING_STEPS, learningStepFor, learningStepIndex } from '../src/learning-flow.js'

const expected = {
  '①发现': ['observe', '运行观察', 0],
  '②定位': ['explain', '定位原因', 1],
  '③归因': ['explain', '定位原因', 1],
  '④修复': ['verify', '修改验证', 2],
  '⑤验证': ['verify', '修改验证', 2],
  '⑥内化': ['transfer', '总结迁移', 3],
}

assert.equal(LEARNING_STEPS.length, 4)
for (const [stage, [id, name, index]] of Object.entries(expected)) {
  const step = learningStepFor(stage)
  assert.equal(step.id, id, stage)
  assert.equal(step.name, name, stage)
  assert.equal(learningStepIndex(stage), index, stage)
  assert.ok(step.goal.length >= 12, `${stage} 必须有可读的当前目标`)
}

assert.equal(learningStepFor('未知阶段').id, 'observe')
console.log('学习四步映射：6 个内部阶段全部通过')
