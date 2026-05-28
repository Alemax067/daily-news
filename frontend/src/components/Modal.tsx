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
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-md p-6 m-4"
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
