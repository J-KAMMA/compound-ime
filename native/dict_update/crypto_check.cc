// 暗号の部品の照らし合わせの道具。標準入力の行を読み、答えを1行ずつ出す。
//   v <署名の16進> <公開鍵の16進> <文の16進>   署名が合えば 1、合わなければ 0
//   sha <文の16進>                              SHA-256 の16進
// tools/dict_update_crypto_check.py が、python の cryptography・hashlib の結果と照らし合わせる。
#include "dict_update/crypto.h"
#include <iostream>
#include <string>
using namespace dict_update;
int main(){
  std::string line;
  while (std::getline(std::cin, line)) {
    // kind sigHex pubHex msgHex | sha msgHex
    size_t a=line.find(' '); std::string kind=line.substr(0,a);
    if(kind=="sha"){ std::string m; HexDecode(line.substr(a+1), &m); std::cout<<Sha256Hex(m)<<"\n"; continue; }
    size_t b=line.find(' ',a+1), c=line.find(' ',b+1);
    std::string sig,pub,msg; HexDecode(line.substr(a+1,b-a-1),&sig); HexDecode(line.substr(b+1,c-b-1),&pub); HexDecode(line.substr(c+1),&msg);
    std::cout<<(Ed25519Verify(sig,msg,pub)?1:0)<<"\n";
  }
}
