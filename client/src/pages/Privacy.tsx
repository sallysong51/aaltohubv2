/**
 * Privacy Policy Page
 * Design Philosophy: Telegram-Native Brutalism
 */
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useLocation } from 'wouter';
import { ArrowLeft } from 'lucide-react';

export default function Privacy() {
  const [, setLocation] = useLocation();

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b-4 border-border bg-card">
        <div className="container py-6">
          <Button
            variant="outline"
            onClick={() => setLocation('/')}
            className="mb-4 border-2"
          >
            <ArrowLeft className="mr-2 h-4 w-4" />
            홈으로
          </Button>
          <h1 className="text-4xl font-bold">개인정보 처리방침</h1>
          <p className="text-muted-foreground mt-2">
            최종 업데이트: 2026년 2월 5일
          </p>
        </div>
      </div>

      {/* Content */}
      <div className="container py-8">
        <Card className="brutalist-card border-4">
          <CardContent className="p-8 space-y-6">
            <section>
              <h2 className="text-2xl font-bold mb-4">1. 수집하는 개인정보</h2>
              <p className="text-muted-foreground mb-2">
                AaltoHub는 다음과 같은 개인정보를 수집합니다:
              </p>
              <ul className="list-disc list-inside space-y-2 text-muted-foreground ml-4">
                <li><strong>텔레그램 계정 정보:</strong> 사용자 ID, 사용자명, 이름, 전화번호</li>
                <li><strong>그룹 정보:</strong> 등록한 텔레그램 그룹의 ID, 이름, 멤버 수</li>
                <li><strong>메시지 데이터:</strong> 등록된 그룹의 공개 메시지 내용, 발신자 정보, 미디어</li>
                <li><strong>세션 정보:</strong> 텔레그램 로그인 세션 (암호화 저장)</li>
              </ul>
            </section>

            <section>
              <h2 className="text-2xl font-bold mb-4">2. 개인정보 수집 목적</h2>
              <p className="text-muted-foreground mb-2">
                수집된 개인정보는 다음 목적으로만 사용됩니다:
              </p>
              <ul className="list-disc list-inside space-y-2 text-muted-foreground ml-4">
                <li>텔레그램 그룹 메시지 수집 및 표시</li>
                <li>사용자 인증 및 권한 관리</li>
                <li>그룹 등록 및 관리</li>
                <li>서비스 품질 개선 및 오류 분석</li>
              </ul>
            </section>

            <section>
              <h2 className="text-2xl font-bold mb-4">3. 개인정보 보관 및 보호</h2>
              <p className="text-muted-foreground mb-2">
                AaltoHub는 다음과 같은 방법으로 개인정보를 보호합니다:
              </p>
              <ul className="list-disc list-inside space-y-2 text-muted-foreground ml-4">
                <li><strong>암호화:</strong> 텔레그램 세션 데이터는 AES-256으로 암호화하여 저장</li>
                <li><strong>접근 제어:</strong> Row Level Security (RLS)를 통한 데이터베이스 접근 제어</li>
                <li><strong>보안 서버:</strong> AWS EC2 및 Supabase의 보안 인프라 사용</li>
                <li><strong>최소 권한:</strong> 필요한 최소한의 권한만 요청</li>
              </ul>
            </section>

            <section>
              <h2 className="text-2xl font-bold mb-4">4. 개인정보 제3자 제공</h2>
              <p className="text-muted-foreground">
                AaltoHub는 사용자의 개인정보를 제3자에게 제공하지 않습니다. 
                단, 법적 의무를 준수하기 위해 필요한 경우 관련 법령에 따라 제공될 수 있습니다.
              </p>
            </section>

            <section>
              <h2 className="text-2xl font-bold mb-4">5. 개인정보 보유 기간</h2>
              <p className="text-muted-foreground mb-2">
                개인정보는 다음 기간 동안 보유됩니다:
              </p>
              <ul className="list-disc list-inside space-y-2 text-muted-foreground ml-4">
                <li><strong>계정 정보:</strong> 회원 탈퇴 시까지</li>
                <li><strong>메시지 데이터:</strong> 그룹 등록 해제 시까지</li>
                <li><strong>세션 정보:</strong> 로그아웃 또는 회원 탈퇴 시 즉시 삭제</li>
              </ul>
            </section>

            <section>
              <h2 className="text-2xl font-bold mb-4">6. 사용자 권리</h2>
              <p className="text-muted-foreground mb-2">
                사용자는 다음과 같은 권리를 가집니다:
              </p>
              <ul className="list-disc list-inside space-y-2 text-muted-foreground ml-4">
                <li><strong>열람 권리:</strong> 자신의 개인정보를 열람할 수 있습니다</li>
                <li><strong>정정 권리:</strong> 잘못된 정보를 수정할 수 있습니다</li>
                <li><strong>삭제 권리:</strong> 계정 삭제를 통해 모든 개인정보를 삭제할 수 있습니다</li>
                <li><strong>처리 정지 권리:</strong> 개인정보 처리의 정지를 요청할 수 있습니다</li>
              </ul>
            </section>

            <section>
              <h2 className="text-2xl font-bold mb-4">7. 쿠키 사용</h2>
              <p className="text-muted-foreground">
                AaltoHub는 사용자 인증을 위해 JWT 토큰을 사용합니다. 
                이 토큰은 브라우저의 로컬 스토리지에 저장되며, 로그아웃 시 자동으로 삭제됩니다.
              </p>
            </section>

            <section>
              <h2 className="text-2xl font-bold mb-4">8. 아동의 개인정보 보호</h2>
              <p className="text-muted-foreground">
                AaltoHub는 만 14세 미만 아동의 개인정보를 수집하지 않습니다. 
                만 14세 미만 아동이 서비스를 이용하는 경우, 법정대리인의 동의가 필요합니다.
              </p>
            </section>

            <section>
              <h2 className="text-2xl font-bold mb-4">9. 개인정보 처리방침 변경</h2>
              <p className="text-muted-foreground">
                본 개인정보 처리방침은 법령 또는 서비스의 변경사항을 반영하기 위해 수정될 수 있습니다. 
                변경 시 웹사이트를 통해 공지하며, 중요한 변경사항은 이메일로 개별 통지합니다.
              </p>
            </section>

            <section>
              <h2 className="text-2xl font-bold mb-4">10. 문의</h2>
              <p className="text-muted-foreground mb-2">
                개인정보 처리방침에 대한 문의사항이 있으시면 아래로 연락주시기 바랍니다:
              </p>
              <ul className="list-none space-y-2 text-muted-foreground ml-4">
                <li><strong>이메일:</strong> privacy@aaltohub.com</li>
                <li><strong>웹사이트:</strong> https://aaltohub.com</li>
              </ul>
            </section>

            <section className="pt-6 border-t-2 border-border">
              <p className="text-sm text-muted-foreground">
                본 개인정보 처리방침은 2026년 2월 5일부터 시행됩니다.
              </p>
            </section>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
