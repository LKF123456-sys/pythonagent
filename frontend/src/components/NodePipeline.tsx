// 节点流水线动画：preprocess → supervisor → search/rag → answer → store_memory
import { motion, AnimatePresence } from "framer-motion";
import { NODE_LABELS, type PipelineStage } from "../store/chat";
import type { PipelineNode } from "../types";

interface Props {
  stages: PipelineStage[];
  visible: boolean;
}

export function NodePipeline({ stages, visible }: Props) {
  return (
    <AnimatePresence>
      {visible && stages.length > 0 && (
        <motion.div
          className="pipeline"
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          transition={{ duration: 0.22 }}
        >
          {stages.map((stage, i) => (
            <span key={stage.node} style={{ display: "inline-flex", alignItems: "center" }}>
              {i > 0 && <span className="pipeline-arrow">→</span>}
              <motion.span
                className={`pipeline-node ${stage.state}`}
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.2 }}
              >
                <span className="p-dot" />
                {NODE_LABELS[stage.node as PipelineNode] ?? stage.node}
              </motion.span>
            </span>
          ))}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
