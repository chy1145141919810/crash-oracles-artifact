(require '[elle.core :as elle] '[elle.graph :as eg] '[bifurcan-clj.graph :as g]
         '[jepsen.history :as h] '[clojure.edn :as edn] '[clojure.java.io :as io])
(import '(java.io PushbackReader))
(defn read-history [f]
  (with-open [r (PushbackReader. (io/reader f))]
    (->> (repeatedly #(edn/read {:eof nil} r)) (take-while identity) vec)))
(let [[f] *command-line-args*
      hist (h/history (read-history f))
      rt (:graph (elle/realtime-graph hist))
      sccs (eg/strongly-connected-components rt)]
  (println "SCCs with more than one op:" (count (seq sccs)))
  (doseq [scc (take 3 (seq sccs))]
    (println "  scc:" (sort (map :index (seq scc))))
    (doseq [op (sort-by :index (seq scc))]
      (println "    " (:index op) (:type op) "proc" (:process op) "->" (sort (map :index (g/out rt op))) "in<-" (sort (map :index (g/in rt op)))))))
(shutdown-agents)
(System/exit 0)