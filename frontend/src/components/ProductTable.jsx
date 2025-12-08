import { motion } from "framer-motion";

export default function ProductTable({ produtos }) {
  return (
    <table className="w-full text-sm md:text-base">
      <thead className="text-white/60 uppercase">
        <tr>
          <th className="p-2">Produto</th>
          <th className="p-2">PIX</th>
          <th className="p-2">Parcelado</th>
          <th className="p-2">Print</th>
        </tr>
      </thead>
      <tbody>
        {produtos.map((item, i) => (
          <motion.tr
            key={i}
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.03 }}
            className="border-t border-white/10"
          >
            <td className="p-2">{item.nome}</td>
            <td className="p-2">{item.pix}</td>
            <td className="p-2">{item.parcelado}</td>
            <td className="p-2">
              <a
                href={`http://127.0.0.1:5000/prints/${item.print}`}
                target="_blank"
                className="text-neon-purple underline"
              >
                Ver print
              </a>
            </td>
          </motion.tr>
        ))}
      </tbody>
    </table>
  );
}
