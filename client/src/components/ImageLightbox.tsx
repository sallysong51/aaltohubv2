import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { X, ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';

export interface PhotoEntry {
  url: string;
  alt: string;
  messageId: string | number;
}

interface ImageLightboxProps {
  photos: PhotoEntry[];
  initialIndex: number;
  isOpen: boolean;
  onClose: () => void;
}

export default function ImageLightbox({ photos, initialIndex, isOpen, onClose }: ImageLightboxProps) {
  const [currentIndex, setCurrentIndex] = useState(initialIndex);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setCurrentIndex(initialIndex);
      setLoaded(false);
    }
  }, [isOpen, initialIndex]);

  const navigate = useCallback((dir: number) => {
    setCurrentIndex(prev => {
      const next = prev + dir;
      if (next < 0 || next >= photos.length) return prev;
      setLoaded(false);
      return next;
    });
  }, [photos.length]);

  useEffect(() => {
    if (!isOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowLeft') navigate(-1);
      else if (e.key === 'ArrowRight') navigate(+1);
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isOpen, onClose, navigate]);

  // Preload adjacent images
  useEffect(() => {
    if (!isOpen) return;
    [currentIndex - 1, currentIndex + 1].forEach(i => {
      if (i >= 0 && i < photos.length) {
        const img = new Image();
        img.src = photos[i].url;
      }
    });
  }, [isOpen, currentIndex, photos]);

  // Prevent body scroll when open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
      return () => { document.body.style.overflow = ''; };
    }
  }, [isOpen]);

  if (!isOpen || photos.length === 0) return null;

  const photo = photos[currentIndex];
  if (!photo) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center animate-in fade-in-0 duration-200"
      role="dialog"
      aria-modal="true"
      aria-label="이미지 뷰어"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      {/* Close button */}
      <Button
        variant="ghost"
        size="icon"
        className="absolute top-4 right-4 text-white hover:bg-white/20 z-10"
        onClick={onClose}
      >
        <X className="h-6 w-6" />
      </Button>

      {/* Counter */}
      {photos.length > 1 && (
        <div className="absolute top-4 left-4 text-white/70 text-sm z-10">
          {currentIndex + 1} / {photos.length}
        </div>
      )}

      {/* Navigation */}
      {currentIndex > 0 && (
        <Button
          variant="ghost"
          size="icon"
          className="absolute left-4 top-1/2 -translate-y-1/2 text-white hover:bg-white/20 z-10"
          onClick={() => navigate(-1)}
        >
          <ChevronLeft className="h-8 w-8" />
        </Button>
      )}
      {currentIndex < photos.length - 1 && (
        <Button
          variant="ghost"
          size="icon"
          className="absolute right-4 top-1/2 -translate-y-1/2 text-white hover:bg-white/20 z-10"
          onClick={() => navigate(+1)}
        >
          <ChevronRight className="h-8 w-8" />
        </Button>
      )}

      {/* Image */}
      <img
        src={photo.url}
        alt={photo.alt}
        className={`max-h-[90vh] max-w-[90vw] object-contain transition-opacity duration-200 ${loaded ? 'opacity-100' : 'opacity-0'}`}
        onLoad={() => setLoaded(true)}
      />
    </div>,
    document.body,
  );
}
