interface Props {
  value: number;
  onChange: (next: number) => void;
  min: number;
  max: number;
  step?: number;
  disabled?: boolean;
  className?: string;
}

/**
 * 整数选择器:input + 上下箭头按钮。不响应鼠标滚轮(用户已确认)。
 * 上下越界时按钮自动禁用,文本输入会被 clamp。
 */
export function NumberInput({
  value,
  onChange,
  min,
  max,
  step = 1,
  disabled,
  className = "",
}: Props) {
  function clamp(n: number): number {
    if (Number.isNaN(n)) return min;
    if (n < min) return min;
    if (n > max) return max;
    return Math.round(n);
  }
  const dec = () => onChange(clamp(value - step));
  const inc = () => onChange(clamp(value + step));
  return (
    <div className={`inline-flex items-stretch border border-slate-300 rounded-md overflow-hidden ${className}`}>
      <button
        type="button"
        disabled={disabled || value <= min}
        onClick={dec}
        className="px-2 bg-slate-50 hover:bg-slate-100 text-slate-600 disabled:opacity-40 disabled:cursor-not-allowed border-r border-slate-300"
        aria-label="减"
      >
        −
      </button>
      <input
        type="number"
        inputMode="numeric"
        value={value}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(e) => onChange(clamp(parseInt(e.target.value, 10)))}
        onWheel={(e) => (e.target as HTMLInputElement).blur()}
        className="w-16 text-center text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
      />
      <button
        type="button"
        disabled={disabled || value >= max}
        onClick={inc}
        className="px-2 bg-slate-50 hover:bg-slate-100 text-slate-600 disabled:opacity-40 disabled:cursor-not-allowed border-l border-slate-300"
        aria-label="加"
      >
        +
      </button>
    </div>
  );
}
