  // (exp/garble only) JAEN_DEBUG=1: how the typed keys were read and split.
  if (std::getenv("JAEN_DEBUG") != nullptr) {
    std::string line = "JAEN chunks";
    for (const jaen::Chunk& c : chunks) {
      line += " [" + c.raw + "|" + c.conversion + "|" + c.pending + "]";
    }
    line += " pieces";
    for (size_t p = 0; p < pieces.size(); ++p) {
      line += std::string(" ") + (pieces[p].english ? "E:" : "J:") + texts[p];
    }
    line += split ? " split" : " nosplit";
    std::fprintf(stderr, "%s\n", line.c_str());
  }
