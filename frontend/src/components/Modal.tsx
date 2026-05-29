import type { PropsWithChildren } from "react";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
}

export function Modal({
  open,
  onClose,
  title,
  children,
}: PropsWithChildren<ModalProps>) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-end sm:items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white w-full sm:w-auto sm:max-w-md rounded-t-xl sm:rounded-lg shadow-xl p-4 sm:p-6 max-h-[90dvh] overflow-y-auto safe-bottom"
        onClick={(e) => e.stopPropagation()}
      >
        {title && (
          <h2 className="text-lg font-semibold mb-4">{title}</h2>
        )}
        {children}
      </div>
    </div>
  );
}
