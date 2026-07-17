export const LEARNING_STEPS = [
  {
    id: 'observe',
    name: '运行观察',
    goal: '先运行一次，只看真实发生了什么。',
    stages: ['①发现'],
  },
  {
    id: 'explain',
    name: '定位原因',
    goal: '找到异常经过的位置，只追一个值并说清为什么。',
    stages: ['②定位', '③归因'],
  },
  {
    id: 'verify',
    name: '修改验证',
    goal: '只做一个最小修改，再用真实运行验证判断。',
    stages: ['④修复', '⑤验证'],
  },
  {
    id: 'transfer',
    name: '总结迁移',
    goal: '留下一条下次遇到相似问题也能用的判断方法。',
    stages: ['⑥内化'],
  },
]

const STAGE_TO_STEP = new Map(
  LEARNING_STEPS.flatMap((step, index) => step.stages.map((stage) => [stage, { ...step, index }])),
)

export function learningStepFor(stage) {
  return STAGE_TO_STEP.get(stage) || { ...LEARNING_STEPS[0], index: 0 }
}

export function learningStepIndex(stage) {
  return learningStepFor(stage).index
}
