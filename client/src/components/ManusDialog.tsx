import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";

interface ManusDialogProps {
  title?: string;
  logo?: string;
  open?: boolean;
  onLogin: () => void;
  onOpenChange?: (open: boolean) => void;
  onClose?: () => void;
}

export function ManusDialog({
  title,
  logo,
  open = false,
  onLogin,
  onOpenChange,
  onClose,
}: ManusDialogProps) {
  const [internalOpen, setInternalOpen] = useState(open);

  useEffect(() => {
    if (!onOpenChange) {
      setInternalOpen(open);
    }
  }, [open, onOpenChange]);

  const handleOpenChange = (nextOpen: boolean) => {
    if (onOpenChange) {
      onOpenChange(nextOpen);
    } else {
      setInternalOpen(nextOpen);
    }

    if (!nextOpen) {
      onClose?.();
    }
  };

  return (
    <Dialog
      open={onOpenChange ? open : internalOpen}
      onOpenChange={handleOpenChange}
    >
      <DialogContent className="bg-card rounded-2xl w-[420px] border border-border shadow-lg shadow-black/10 p-0 gap-0 text-center">
        <div className="flex flex-col items-center gap-3 p-8 pt-10">
          {logo ? (
            <div className="w-16 h-16 bg-secondary rounded-2xl border border-border flex items-center justify-center shadow-md shadow-black/5">
              <img src={logo} alt="Dialog graphic" className="w-10 h-10 rounded-lg" />
            </div>
          ) : null}

          {/* Title and subtitle */}
          {title ? (
            <DialogTitle className="text-2xl font-semibold text-foreground leading-8 tracking-tight">
              {title}
            </DialogTitle>
          ) : null}
          <DialogDescription className="text-sm text-muted-foreground leading-6 tracking-normal">
            Please login with Manus to continue
          </DialogDescription>
        </div>

        <DialogFooter className="px-8 py-6 border-t border-border">
          {/* Login button */}
          <Button
            onClick={onLogin}
            className="w-full h-11 bg-primary hover:bg-primary/90 text-primary-foreground rounded-xl text-sm font-medium leading-5 tracking-normal shadow-md shadow-primary/20 transition-all duration-200"
          >
            Login with Manus
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
