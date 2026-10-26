#include "md.hpp"
#include <chrono>
#include <thread>
#ifdef _WIN32
#include <windows.h>
#endif
// Argumentos sempre em UTF-8; no Windows vêm de wmain (UTF-16) para aceitar
// caminhos com acentos (ex.: C:\Users\José\...), independentemente da página de código.
static int run(int argc,char** argv);
#ifdef _WIN32
int wmain(int argc,wchar_t** wargv) {
    std::vector<std::string> args; std::vector<char*> ptrs;
    for(int i=0;i<argc;++i) {
        int n=WideCharToMultiByte(CP_UTF8,0,wargv[i],-1,nullptr,0,nullptr,nullptr);
        std::string s(n>0 ? n-1 : 0,'\0');
        if(n>1) WideCharToMultiByte(CP_UTF8,0,wargv[i],-1,s.data(),n,nullptr,nullptr);
        args.push_back(std::move(s));
    }
    for(auto& a:args) ptrs.push_back(a.data());
    ptrs.push_back(nullptr);
    return run(argc,ptrs.data());
}
#else
int main(int argc,char** argv) { return run(argc,argv); }
#endif
static int run(int argc,char** argv) {
    try {
        if(argc==2 && (std::string(argv[1])=="--help" || std::string(argv[1])=="-h")) {
            std::cout<<"Uso: simulator arquivo.cfg [--fps 30]\nSaída: JSON Lines (metadados + quadros); mensagens em stderr.\n"; return 0;
        }
        md::require(argc==2 || (argc==4 && std::string(argv[2])=="--fps"),"Uso: simulator arquivo.cfg [--fps 30]");
        double fps=0;
        if(argc==4) { fps=md::number<double>(argv[3]); md::require(std::isfinite(fps) && fps>0 && fps<=240,"--fps deve estar entre 0 (exclusivo) e 240."); }
        auto config=md::Config::read(std::filesystem::u8path(argv[1]));
        auto geometry=md::Geometry::read(config.geometry);
        md::Simulation simulation(config,std::move(geometry));
        std::cerr<<"Simulação: "<<config.particles<<" partículas; OpenMP: até "<<omp_get_max_threads()<<" threads.\n";
        auto start=std::chrono::steady_clock::now();
        simulation.metadata(std::cout); simulation.frame(std::cout,0);
        auto next_frame=start;
        auto interval=std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(fps>0 ? 1/fps : 0));
        for(int step=1;step<=config.steps;++step) {
            simulation.step();
            if(step%config.output_every==0 || step==config.steps) {
                if(fps>0) {
                    next_frame=std::max(next_frame+interval,std::chrono::steady_clock::now());
                    std::this_thread::sleep_until(next_frame);
                }
                simulation.frame(std::cout,step); if(!std::cout) return 0;
            }
        }
        std::cerr<<"Concluído em "<<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<<" s.\n";
        return 0;
    } catch(const std::exception& e) { std::cerr<<"Erro: "<<e.what()<<'\n'; return 1; }
}
